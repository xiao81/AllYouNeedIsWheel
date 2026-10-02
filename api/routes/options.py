"""
Options API routes
"""

from flask import Blueprint, request, jsonify, current_app, g
from api.services.options_service import OptionsService
import traceback
import logging
import math
from api.services.order_validation import validate_order, positive_number

# Set up logger
logger = logging.getLogger("api.routes.options")

bp = Blueprint("options", __name__, url_prefix="/api/options")
options_service = OptionsService()

# Market status is now checked directly in the route functions


# Helper function to check market status with better error handling
@bp.route("/otm", methods=["GET"])
def otm_options():
    """
    Get option data based on OTM percentage from current price.
    """
    # Get parameters from request
    ticker = request.args.get("tickers")
    otm_percentage = float(request.args.get("otm", 10))
    option_type = request.args.get(
        "optionType"
    )  # Parameter for filtering by option type
    expiration = request.args.get(
        "expiration"
    )  # New parameter for filtering by expiration date

    # Validate option_type if provided
    if option_type and option_type not in ["CALL", "PUT"]:
        return jsonify(
            {"error": f"Invalid option_type: {option_type}. Must be 'CALL' or 'PUT'"}
        ), 400

    # Use the existing module-level instance instead of creating a new one
    # Call the service with appropriate parameters including the new option_type and expiration
    result = options_service.get_otm_options(
        ticker=ticker,
        otm_percentage=otm_percentage,
        option_type=option_type,
        expiration=expiration,
    )

    return jsonify(result)


@bp.route("/stock-price", methods=["GET"])
def get_stock_price():
    """
    Get the current stock price for one or more tickers.
    This is a lightweight endpoint that only returns stock prices.
    """
    # Get ticker(s) from request
    tickers_param = request.args.get("tickers", "")
    if not tickers_param:
        return jsonify({"error": "No tickers provided"}), 400

    # Split tickers on commas if multiple are provided
    tickers = [t.strip() for t in tickers_param.split(",")]

    # Get stock prices for the tickers
    prices = {}
    try:
        for ticker in tickers:
            if ticker:
                # Use the options service to get the stock price without option data
                price = options_service.get_stock_price(ticker)
                prices[ticker] = price

        return jsonify({"status": "success", "data": prices})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error getting stock price for {tickers_param}: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e), "status": "error"}), 500


@bp.route("/order", methods=["POST"])
def save_order():
    """
    Save an option order to the database
    """
    try:
        # Get order data from request
        order_data = request.json
        if not order_data:
            return jsonify({"error": "No order data provided"}), 400

        # Validate required fields
        required_fields = ["ticker", "option_type", "strike", "expiration"]
        for field in required_fields:
            if field not in order_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Save order to database
        order_id = g.order_database.save_order(
            options_service.prepare_drafts([order_data])[0]
        )

        if order_id:
            return jsonify({"success": True, "order_id": order_id}), 201
        else:
            return jsonify({"error": "Failed to save order"}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving order: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/pending-orders", methods=["GET"])
def get_pending_orders():
    """
    Get pending option orders from the database

    Query parameters:
        executed (bool): Whether to fetch executed orders (default: false)
        isRollover (bool): Whether to fetch only rollover orders (default: None = all orders)
    """
    try:
        # Get executed parameter (optional)
        executed = request.args.get("executed", "false").lower() == "true"

        # Get isRollover parameter (optional)
        is_rollover_param = request.args.get("isRollover")
        is_rollover = None
        if is_rollover_param is not None:
            is_rollover = is_rollover_param.lower() == "true"

        # Get pending orders from database
        orders = g.order_database.get_pending_orders(
            executed=executed, isRollover=is_rollover
        )

        return jsonify({"orders": orders})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error getting pending orders: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/order/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    """
    Delete/cancel an order from the database.

    Args:
        order_id (int): ID of the order to delete

    Returns:
        JSON response with success status
    """
    logger.info(f"DELETE /order/{order_id} request received")

    try:
        # Get the database instance
        db = current_app.config.get("database")
        if not db:
            logger.error("Database not initialized")
            return jsonify({"error": "Database not initialized"}), 500

        # Try to get the order first to ensure it exists
        order = db.get_order(order_id)
        if not order:
            logger.error(f"Order with ID {order_id} not found")
            return jsonify({"error": f"Order with ID {order_id} not found"}), 404

        # Delete the order
        success = db.delete_order(order_id)

        if success:
            logger.info(f"Order with ID {order_id} successfully deleted")
            return jsonify(
                {"success": True, "message": f"Order with ID {order_id} deleted"}
            ), 200
        else:
            logger.error(f"Failed to delete order with ID {order_id}")
            return jsonify({"error": "Failed to delete order"}), 500

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error deleting order: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/orders/prepare-submission", methods=["POST"])
def prepare_submission():
    """Verify prices and save pending drafts before showing final confirmation."""
    try:
        body = request.get_json(silent=True)
        ids = body.get("order_ids") if isinstance(body, dict) else None
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 100
            or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("Choose between 1 and 100 distinct draft orders.")
        db = options_service.db
        originals = [db.get_order(order_id) for order_id in ids]
        if any(not order or order["status"] != "pending" for order in originals):
            return jsonify(error="Only unsubmitted drafts can be prepared."), 409
        prepared = options_service.prepare_submission_prices(originals)
        db.update_draft_prices(originals, prepared)
        return jsonify(orders=prepared)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        logger.exception("Cannot prepare order prices")
        return jsonify(error="Could not verify prices. No orders were sent."), 502


@bp.route("/execute/<int:order_id>", methods=["POST"])
def execute_order(order_id):
    """
    Execute an order by sending it to TWS.

    Args:
        order_id (int): ID of the order to execute

    Returns:
        JSON response with execution details
    """
    logger.info(f"POST /execute/{order_id} request received")

    try:
        # Get the database instance
        db = current_app.config.get("database")
        if not db:
            logger.error("Database not initialized")
            return jsonify({"error": "Database not initialized"}), 500

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Order request must be an object."), 400
        if payload.get("expected_order") is not None:
            current = db.get_order(order_id)
            if not current:
                return jsonify(error="Order no longer exists. Refresh the queue."), 409
            expected = validate_order(payload["expected_order"])
            actual = validate_order(current)
            fields = (
                "ticker",
                "option_type",
                "action",
                "strike",
                "expiration",
                "quantity",
                "order_type",
                "limit_price",
            )
            if any(expected.get(key) != actual.get(key) for key in fields):
                return jsonify(
                    error="Order changed after review. Refresh the queue and review it again."
                ), 409
        if (
            payload.get("bulk")
            and db.get_order(order_id)
            and db.get_order(order_id).get("isRollover")
        ):
            return jsonify(
                error="Submit rollover legs individually after confirming the closing fill."
            ), 409

        # Use the options service to execute the order
        response, status_code = options_service.execute_order(order_id, db)

        # Return the response from the service
        return jsonify(response), status_code

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error executing order: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/check-orders", methods=["POST"])
def check_orders():
    """
    Check status of pending/processing orders with TWS API and update them in the database.

    Returns:
        JSON response with updated orders
    """
    logger.info("POST /check-orders request received")

    try:
        # Use the options service to check and update order statuses
        response = options_service.check_pending_orders()

        # Return the response from the service
        return jsonify(response), 200 if response.get("success") else 503

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error checking orders: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/rollover", methods=["POST"])
def rollover_option():
    """
    Create orders to roll over an option position.

    This creates two orders:
    1. Buy order to close the current option position
    2. Sell order to open a new option position

    Returns:
        JSON response with created orders
    """
    logger.info("POST /rollover request received")

    try:
        # Get order data from request
        rollover_data = request.json
        if not isinstance(rollover_data, dict) or not rollover_data:
            return jsonify({"error": "No rollover data provided"}), 400

        # Validate required fields for current option
        required_fields = [
            "ticker",
            "current_option_type",
            "current_strike",
            "current_expiration",
            "new_strike",
            "new_expiration",
            "quantity",
        ]
        for field in required_fields:
            if field not in rollover_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        if str(rollover_data["new_expiration"]) <= str(
            rollover_data["current_expiration"]
        ):
            return jsonify(
                error="Replacement expiration must be later than the current expiration"
            ), 400

        # Create buy order to close current position
        buy_order = {
            "ticker": rollover_data["ticker"],
            "option_type": rollover_data["current_option_type"],
            "strike": rollover_data["current_strike"],
            "expiration": rollover_data["current_expiration"],
            "action": "BUY",  # Buy to close
            "quantity": rollover_data["quantity"],
            "order_type": rollover_data.get("current_order_type", "MARKET"),
            "limit_price": rollover_data.get("current_limit_price"),  # Price per share
            "bid": rollover_data.get("current_bid", 0),
            "ask": rollover_data.get("current_ask", 0),
            "isRollover": True,
        }

        # Create sell order for new position
        sell_order = {
            "ticker": rollover_data["ticker"],
            "option_type": rollover_data["current_option_type"],  # Same option type
            "strike": rollover_data["new_strike"],
            "expiration": rollover_data["new_expiration"],
            "action": "SELL",  # Sell to open
            "quantity": rollover_data["quantity"],
            "order_type": rollover_data.get("new_order_type", "LIMIT"),
            "limit_price": rollover_data.get("new_limit_price", 0),  # Price per share
            "bid": rollover_data.get("new_bid", 0),
            "ask": rollover_data.get("new_ask", 0),
            "isRollover": True,
        }

        # Save orders to database
        buy_order_id, sell_order_id = g.order_database.save_orders(
            options_service.prepare_drafts([buy_order, sell_order])
        )

        if buy_order_id and sell_order_id:
            return jsonify(
                {
                    "success": True,
                    "buy_order_id": buy_order_id,
                    "sell_order_id": sell_order_id,
                    "message": "Rollover orders created successfully",
                }
            ), 201
        else:
            return jsonify(
                {"error": "Failed to create one or more rollover orders"}
            ), 500

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating rollover orders: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/order/<int:order_id>/draft", methods=["DELETE"])
def cancel_draft(order_id):
    """Cancel only an unsent draft, even while broker scans are running."""
    db = g.order_database
    if db.cancel_pending_order(order_id):
        return jsonify(success=True, status="canceled")
    order = db.get_order(order_id)
    if not order:
        return jsonify(error="Order not found"), 404
    if order["status"] == "canceled":
        return jsonify(success=True, status="canceled")
    return jsonify(
        error="Order is no longer a draft. Cancel submitted orders in IBKR. Refresh the queue to review its status."
    ), 409


@bp.route("/cancel/<int:order_id>", methods=["POST"])
def cancel_order(order_id):
    """Legacy endpoint: only local drafts can be canceled by the dashboard."""
    return cancel_draft(order_id)


@bp.route("/order/<int:order_id>/quantity", methods=["PUT"])
def update_order_quantity(order_id):
    """
    Update the quantity of a specific order

    Args:
        order_id (int): ID of the order to update

    Returns:
        JSON response with success status
    """
    logger.info(f"PUT /order/{order_id}/quantity request received")

    try:
        # Get request data
        request_data = request.json
        if not request_data or "quantity" not in request_data:
            logger.error("Missing quantity in request")
            return jsonify({"error": "Missing quantity in request"}), 400

        quantity_value = positive_number(request_data["quantity"], "Quantity")
        if not quantity_value.is_integer():
            return jsonify(error="Quantity must be a whole number"), 400
        quantity = int(quantity_value)
        if quantity <= 0:
            logger.error(f"Invalid quantity: {quantity}")
            return jsonify({"error": "Quantity must be greater than 0"}), 400

        # Get the database instance
        db = g.order_database
        if not db:
            logger.error("Database not initialized")
            return jsonify({"error": "Database not initialized"}), 500

        # Try to get the order first to ensure it exists
        order = db.get_order(order_id)
        if not order:
            logger.error(f"Order with ID {order_id} not found")
            return jsonify({"error": f"Order with ID {order_id} not found"}), 404

        # Check if order is in editable state
        if order["status"] != "pending":
            logger.error(
                f"Cannot update quantity for order with status '{order['status']}'"
            )
            return jsonify(
                {"error": "Cannot update quantity for non-pending orders"}
            ), 400

        # Update the order quantity
        success = db.update_order_quantity(order_id, quantity)

        if success:
            logger.info(f"Order with ID {order_id} quantity updated to {quantity}")
            return jsonify(
                {
                    "success": True,
                    "message": f"Order quantity updated to {quantity}",
                    "order_id": order_id,
                    "quantity": quantity,
                }
            ), 200
        else:
            logger.error(f"Failed to update quantity for order with ID {order_id}")
            return jsonify({"error": "Failed to update order quantity"}), 500

    except ValueError as ve:
        logger.error(f"Invalid quantity value: {str(ve)}")
        return jsonify({"error": "Invalid quantity value"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error updating order quantity: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/expirations", methods=["GET"])
def get_option_expirations():
    """
    Get available expiration dates for options of a given ticker.

    Query parameters:
        ticker (str): The ticker symbol (e.g., 'NVDA')

    Returns:
        JSON response with a list of available expiration dates
    """
    logger.info("GET /expirations request received")

    try:
        # Get ticker from request
        ticker = request.args.get("ticker")
        if not ticker:
            return jsonify({"error": "No ticker provided"}), 400

        # Call the service method to get option expirations
        result = options_service.get_option_expirations(ticker)

        # Check if there was an error
        if "error" in result:
            error_message = result["error"]
            logger.error(f"Error getting expirations for {ticker}: {error_message}")
            return jsonify({"error": error_message}), 404

        # Return successful response
        return jsonify(result)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(
            f"Error getting option expirations for {request.args.get('ticker', 'unknown')}: {str(e)}"
        )
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@bp.route("/scan-batch", methods=["GET"])
@bp.route("/scan", methods=["GET"])
def scan_options():
    try:
        batch = request.path.endswith("/scan-batch")
        tickers = list(
            dict.fromkeys(
                t.strip().upper()
                for t in request.args.get("tickers" if batch else "ticker", "").split(
                    ","
                )
                if t.strip()
            )
        )
        if not tickers or len(tickers) > (20 if batch else 1):
            raise ValueError(
                "Choose between 1 and 20 symbols" if batch else "Enter one ticker"
            )
        ticker = tickers[0]
        if any(
            len(t) > 20 or not all(c.isalnum() or c in ".- " for c in t)
            for t in tickers
        ):
            raise ValueError("Enter a valid ticker")
        option_type = request.args.get("type", "PUT").upper()
        if option_type not in ("CALL", "PUT"):
            raise ValueError("Type must be CALL or PUT")
        low = float(request.args.get("delta_min", 0.05))
        high = float(request.args.get("delta_max", 0.10))
        if not (math.isfinite(low) and math.isfinite(high) and 0 < low <= high < 1):
            raise ValueError("Delta bounds must satisfy 0 < minimum ≤ maximum < 1")
        expiration = request.args.get("expiration")
        if expiration:
            from datetime import datetime

            if len(expiration) != 8 or not expiration.isdigit():
                raise ValueError("Expiration must use YYYYMMDD")
            datetime.strptime(expiration, "%Y%m%d")
        scanner = options_service.get_scanner()
        scan = scanner.scan_many if batch else scanner.scan
        result = scanner.ib._run(
            scan(
                tickers if batch else ticker,
                option_type,
                request.args.get("expiration"),
                low,
                high,
                request.args.get("refresh") == "true",
                **(
                    {
                        "on_result": request.environ.get("wheel.scan_emit"),
                        "cancelled": request.environ.get("wheel.scan_cancelled"),
                    }
                    if batch
                    else {}
                ),
            )
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        logger.exception("Option scan failed")
        return jsonify(error=str(exc) or "Broker request timed out"), 503


@bp.route("/orders/batch", methods=["POST"])
def save_order_batch():
    """Validate all selected drafts, then save atomically. No broker orders."""
    try:
        body = request.get_json(silent=True)
        orders = body.get("orders") if isinstance(body, dict) else None
        if not isinstance(orders, list) or not 1 <= len(orders) <= 20:
            raise ValueError("Choose between 1 and 20 drafts")
        validated = options_service.prepare_drafts(orders)
        ids = g.order_database.save_orders(validated)
        return jsonify(success=True, order_ids=ids), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        logger.exception("Failed to save draft batch")
        return jsonify(error="Could not save drafts. No drafts were saved."), 500


@bp.route("/order/<int:order_id>/local", methods=["DELETE"])
def remove_local_order(order_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("confirm_local_only") is not True:
        return jsonify(error="Confirm removal of the local record only"), 400
    if not options_service.db.remove_local_order(order_id):
        return jsonify(
            error="Record is missing or its status changed. Refresh the queue."
        ), 409
    return jsonify(
        success=True, message="Local record removed. No broker cancellation was sent."
    )
