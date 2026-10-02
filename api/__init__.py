"""
Auto-Trader API
Flask application initialization and configuration.
"""

from flask import Flask, copy_current_request_context, request, jsonify
from core.logging_config import get_logger

# Configure logging
logger = get_logger("autotrader.api", "api")


def create_app(config=None):
    """
    Create and configure the Flask application.

    Args:
        config (dict, optional): Configuration dictionary

    Returns:
        Flask: Configured Flask application
    """
    logger.info("Creating API application")
    app = Flask(
        __name__,
        static_folder="../frontend/static",
        template_folder="../frontend/templates",
    )

    from flask.json.provider import DefaultJSONProvider
    import math

    class FiniteJSONProvider(DefaultJSONProvider):
        def dumps(self, value, **kwargs):
            def clean(item):
                if isinstance(item, float) and not math.isfinite(item):
                    return None
                if isinstance(item, dict):
                    return {key: clean(value) for key, value in item.items()}
                if isinstance(item, (list, tuple)):
                    return [clean(value) for value in item]
                return item

            return super().dumps(clean(value), **kwargs)

    app.json = FiniteJSONProvider(app)

    @app.before_request
    def protect_local_mutations():
        if request.path.startswith("/api/") and request.method in (
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
        ):
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                return jsonify(error="Cross-origin changes are not allowed"), 403
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return jsonify(error="Cross-site changes are not allowed"), 403

    # Default configuration
    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE="sqlite:///:memory:",
    )

    # Override with passed config
    if config:
        app.config.update(config)
        logger.debug("Applied custom configuration")

    # Register blueprints
    from api.routes import portfolio, options, recommendations, settings

    app.register_blueprint(portfolio.bp)
    app.register_blueprint(options.bp)
    app.register_blueprint(recommendations.bp)
    app.register_blueprint(settings.bp)

    # ib_async objects belong to one event loop. Keep broker work on one thread
    # per process, even when Flask serves concurrent HTTP requests.
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from functools import wraps
    from config import Config
    from db.database import OptionsDatabase

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="broker")
    app.extensions["broker_executor"] = executor
    options.options_service.portfolio_service = portfolio.portfolio_service

    def broker_view(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            streaming = (
                request.endpoint == "options.scan_options"
                and request.path.endswith("/scan-batch")
                and request.args.get("stream") == "true"
            )
            if streaming:
                from queue import Queue, Empty
                from threading import Event
                from flask import Response

                messages, disconnected = Queue(), Event()
                request.environ["wheel.scan_emit"] = lambda result: messages.put(
                    {"type": "result", "result": result}
                )
                request.environ["wheel.scan_cancelled"] = disconnected.is_set

            @copy_current_request_context
            def run():
                try:
                    asyncio.get_event_loop()
                except RuntimeError:
                    asyncio.set_event_loop(asyncio.new_event_loop())
                config = Config()
                # Validate after queueing: a second tab could have switched
                # accounts while this request waited for the broker thread.
                from core.settings import read_profiles, public_profiles

                if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                    expected = public_profiles(read_profiles())["revision"]
                    revision = request.headers.get("X-Wheel-Profile")
                    if request.endpoint.startswith("options.") or revision:
                        if revision != expected:
                            return jsonify(
                                error="Connection settings changed. Reload the page before changing orders."
                            ), 409
                for service in (options.options_service, portfolio.portfolio_service):
                    if service.config.to_dict() != config.to_dict():
                        if service.connection:
                            service.connection.disconnect()
                        service.connection = None
                        service.config = config
                        if hasattr(service, "_portfolio_cache"):
                            service._portfolio_cache = None
                db_path = config.get("db_path") or "options.db"
                from pathlib import Path

                if options.options_service.db.db_path != Path.cwd() / db_path:
                    options.options_service.db = OptionsDatabase(db_path)
                app.config["database"] = options.options_service.db
                return view(*args, **kwargs)

            future = executor.submit(run)
            if not streaming:
                return future.result()

            def finished(done):
                try:
                    with app.app_context():
                        response = app.make_response(done.result())
                        data = response.get_json()
                        messages.put(
                            {
                                "type": "complete"
                                if response.status_code < 400
                                else "error",
                                "data": data,
                            }
                        )
                except Exception:
                    logger.exception("Streaming scan failed")
                    messages.put(
                        {
                            "type": "error",
                            "data": {
                                "error": "Scan failed. Retry the unfinished symbols."
                            },
                        }
                    )

            future.add_done_callback(finished)

            def events():
                try:
                    yield app.json.dumps({"type": "started"}) + "\n"
                    while True:
                        try:
                            message = messages.get(timeout=5)
                        except Empty:
                            yield app.json.dumps({"type": "heartbeat"}) + "\n"
                            continue
                        yield app.json.dumps(message) + "\n"
                        if message["type"] in ("complete", "error"):
                            break
                finally:
                    disconnected.set()

            return Response(
                events(),
                mimetype="application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )

        return wrapped

    def local_order_view(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from flask import g
            from core.settings import read_profiles, public_profiles

            # Snapshot one profile without touching shared broker service state.
            profiles = read_profiles()
            if request.method != "GET":
                if (
                    request.headers.get("X-Wheel-Profile")
                    != public_profiles(profiles)["revision"]
                ):
                    return jsonify(
                        error="Connection settings changed. Reload the page before changing orders."
                    ), 409
            profile = profiles[profiles["mode"]]
            g.order_database = OptionsDatabase(profile.get("db_path") or "options.db")
            return view(*args, **kwargs)

        return wrapped

    for endpoint, view in list(app.view_functions.items()):
        if endpoint in (
            "options.get_pending_orders",
            "options.save_order",
            "options.save_order_batch",
            "options.update_order_quantity",
            "options.rollover_option",
            "options.cancel_draft",
            "options.cancel_order",
        ):
            app.view_functions[endpoint] = local_order_view(view)
        elif endpoint.split(".")[0] in ("portfolio", "options", "settings"):
            app.view_functions[endpoint] = broker_view(view)

    logger.info("Registered API blueprints")

    @app.route("/health")
    def health_check():
        logger.debug("Health check endpoint called")
        return {"status": "healthy"}

    logger.info("API application created successfully")
    return app
