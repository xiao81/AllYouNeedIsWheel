"""Normalize order inputs; all prices are quoted per share."""

import math
from datetime import datetime


def positive_number(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a positive finite number") from None
    if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return number


def validate_order(data):
    if not isinstance(data, dict):
        raise ValueError("Order must be a JSON object")
    order = data.copy()
    ticker = str(order.get("ticker") or "").strip().upper()
    if (
        not ticker
        or len(ticker) > 20
        or not all(c.isalnum() or c in ".- " for c in ticker)
    ):
        raise ValueError("Invalid ticker")
    order["ticker"] = ticker
    option_type = str(order.get("option_type", "")).upper()
    order["option_type"] = {"C": "CALL", "P": "PUT"}.get(option_type, option_type)
    if order["option_type"] not in ("CALL", "PUT"):
        raise ValueError("Option type must be CALL or PUT")
    order["action"] = str(order.get("action", "SELL")).upper()
    if order["action"] not in ("BUY", "SELL"):
        raise ValueError("Action must be BUY or SELL")
    quantity = positive_number(order.get("quantity", 1), "Quantity")
    if not quantity.is_integer():
        raise ValueError("Quantity must be a whole number")
    order["quantity"] = int(quantity)
    order["strike"] = positive_number(order.get("strike"), "Strike")
    expiration = str(order.get("expiration", ""))
    if len(expiration) != 8 or not expiration.isdigit():
        raise ValueError("Expiration must use YYYYMMDD")
    datetime.strptime(expiration, "%Y%m%d")
    order["expiration"] = expiration
    order_type = str(order.get("order_type", "LIMIT")).upper()
    order["order_type"] = {"LMT": "LIMIT", "MKT": "MARKET"}.get(order_type, order_type)
    if order["order_type"] not in ("LIMIT", "MARKET"):
        raise ValueError("Order type must be LIMIT or MARKET")
    if order["order_type"] == "LIMIT":
        price = order.get("limit_price")
        if price is None:
            # Compatibility with existing dashboard orders, which store premium.
            price = order.get("premium")
        order["limit_price"] = positive_number(price, "Limit price")
        order["premium"] = order["limit_price"]
    else:
        order["limit_price"] = None
    return order
