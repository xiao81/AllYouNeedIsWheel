"""Human-friendly broker settings; no username or password is stored."""

from flask import Blueprint, request, jsonify
from core.settings import read_profiles, save_profiles, public_profiles
from core.connection import IBConnection

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@bp.route("", methods=["GET", "PUT"])
def settings():
    try:
        profiles = (
            save_profiles(request.get_json())
            if request.method == "PUT"
            else read_profiles()
        )
        return jsonify(public_profiles(profiles))
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@bp.route("/test", methods=["POST"])
def test_connection():
    profiles = read_profiles()
    profile = profiles[profiles["mode"]]
    connection = IBConnection(
        host=profile["host"],
        port=profile["port"],
        client_id=profile["client_id"],
        readonly=True,
        timeout=5,
    )
    try:
        if not connection.connect():
            return jsonify(
                error="Cannot connect. Open and log in to TWS or IB Gateway, enable API access, and check the port and client ID."
            ), 503
        accounts = connection.ib.managedAccounts()
        if profile.get("account_id") and profile["account_id"] not in accounts:
            return jsonify(
                error="Connected, but the configured account is not available in this session."
            ), 400
        return jsonify(
            success=True,
            accounts=accounts,
            message="Connection verified. No orders were placed.",
        )
    finally:
        connection.disconnect()
