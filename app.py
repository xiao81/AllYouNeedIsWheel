"""
Auto-Trader Web Application
Main entry point for the web application
"""

import os
from flask import render_template, request, redirect, url_for
from api import create_app
from core.logging_config import get_logger

# Configure logging
logger = get_logger("autotrader.app", "api")


# Create Flask application with necessary configs
def create_application():
    # Create the app through the factory function
    app = create_app()

    from api.routes.options import options_service

    app.config["database"] = options_service.db
    return app


# Create the application
app = create_application()


# Web routes
@app.route("/")
def index():
    """
    Render the dashboard page
    """
    logger.info("Rendering dashboard page")
    return render_template("dashboard.html")


@app.route("/portfolio")
def portfolio():
    """
    Render the portfolio page
    """
    logger.info("Rendering portfolio page")
    return render_template("portfolio.html")


@app.route("/options")
def options():
    """
    Temporarily redirect options page to home
    """
    logger.info("Options page accessed but currently unavailable - redirecting to home")
    return redirect(url_for("index"))


@app.route("/rollover")
def rollover():
    """
    Render the rollover page for options approaching strike price
    """
    logger.info("Rendering rollover page")
    return render_template("rollover.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/recommendations")
def recommendations():
    """
    Temporarily redirect recommendations page to home
    """
    logger.info(
        "Recommendations page accessed but currently unavailable - redirecting to home"
    )
    return redirect(url_for("index"))


@app.errorhandler(404)
def page_not_found(e):
    """
    Handle 404 errors
    """
    logger.warning(f"404 error: {request.path}")
    return render_template("error.html", error_code=404, message="Page not found"), 404


@app.errorhandler(500)
def server_error(e):
    """
    Handle 500 errors
    """
    logger.error(f"500 error: {str(e)}")
    return render_template("error.html", error_code=500, message="Server error"), 500


if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 8000))

    # Run the application
    logger.info(f"Starting Flask development server on port {port}")
    app.run(host="127.0.0.1", port=port, debug=False)
