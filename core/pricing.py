"""Decimal arithmetic for two-decimal option limit prices."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


def cents(value):
    return float(
        Decimal(str(value))
        .quantize(Decimal("0.0000000001"))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def tick_price(value, increment, action):
    # Remove binary-float noise without discarding genuine half-cent prices.
    price = Decimal(str(value)).quantize(Decimal("0.0000000001"))
    tick = max(Decimal(str(increment)), Decimal("0.01"))
    if tick % Decimal("0.01"):
        raise ValueError("This contract does not support two-decimal limit prices.")
    rounding = ROUND_CEILING if action == "SELL" else ROUND_FLOOR
    result = (price / tick).to_integral_value(rounding=rounding) * tick
    if result <= 0:
        raise ValueError("Limit price is below the minimum price increment.")
    return float(result.quantize(Decimal("0.01")))
