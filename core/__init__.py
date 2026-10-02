"""
AutoTrader Core Module
"""

# Import tools and utilities
from .utils import (
    setup_logging,
    rotate_logs,
    rotate_reports,
    get_closest_friday,
    get_next_monthly_expiration,
    format_currency,
    format_percentage,
    get_strikes_around_price,
)

# Import connection classes
from .connection import IBConnection, Option

__all__ = [
    # Connection
    "IBConnection",
    "Option",
    # Utils
    "rotate_logs",
    "rotate_reports",
    "setup_logging",
    "get_closest_friday",
    "get_next_monthly_expiration",
    "format_currency",
    "format_percentage",
    "get_strikes_around_price",
]
