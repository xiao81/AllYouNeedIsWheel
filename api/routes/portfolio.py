"""
Portfolio API routes
"""

from flask import Blueprint, request, jsonify
from api.services.portfolio_service import PortfolioService

bp = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")
portfolio_service = PortfolioService()


@bp.route("/", methods=["GET"])
def get_portfolio():
    """
    Get the current portfolio information
    """
    try:
        results = portfolio_service.get_portfolio_summary()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/positions", methods=["GET"])
def get_positions():
    """
    Get the current portfolio positions

    Query Parameters:
        type: Filter by position type (STK, OPT). If not provided, returns all positions.
    """
    try:
        # Get the position_type from query parameters
        position_type = request.args.get("type")
        # Validate position_type
        if position_type and position_type not in ["STK", "OPT"]:
            return jsonify(
                {"error": "Invalid position type. Supported types: STK, OPT"}
            ), 400

        results = portfolio_service.get_positions(position_type)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/position-deltas", methods=["GET"])
def get_position_deltas():
    try:
        return jsonify(deltas=portfolio_service.get_position_deltas())
    except Exception:
        return jsonify(
            error="Option deltas are unavailable. Refresh positions to retry."
        ), 503


@bp.route("/weekly-income", methods=["GET"])
def get_weekly_income():
    """
    Get weekly option income from short options expiring this Friday.

    Returns:
        A JSON response containing weekly option income data:
        {
            "positions": [
                {
                    "symbol": "NVDA",
                    "option_type": "P",
                    "strike": 850.0,
                    "expiration": "20240510",
                    "position": 10,
                    "avg_cost": 15.5,
                    "current_price": 15.5,
                    "income": 155.0
                },
                ...
            ],
            "total_income": 155.0,
            "positions_count": 1,
            "this_friday": "20240510"
        }

        Error response:
        {
            "error": "Error message",
            "positions": [],
            "total_income": 0,
            "positions_count": 0
        }
    """
    try:
        results = portfolio_service.get_weekly_option_income()

        if "error" in results:
            return jsonify(
                {
                    "error": results["error"],
                    "positions": [],
                    "total_income": 0,
                    "positions_count": 0,
                }
            ), 500

        return jsonify(results), 200
    except Exception as e:
        return jsonify(
            {"error": str(e), "positions": [], "total_income": 0, "positions_count": 0}
        ), 500
