"""
Utility functions for the autotrader package
"""

import os
import glob
import logging
from datetime import datetime, timedelta, time as datetime_time
import math
import pytz

# Configure logger
logger = logging.getLogger("autotrader.utils")


def rotate_logs(logs_dir="logs", max_logs=5):
    """
    Rotate log files, keeping only the specified number of most recent logs.

    Args:
        logs_dir (str): Directory containing log files
        max_logs (int): Maximum number of log files to keep
    """
    # Get all log files in the logs directory
    log_files = glob.glob(os.path.join(logs_dir, "trader_*.log"))

    # If we don't have too many logs yet, no need to delete any
    if len(log_files) <= max_logs:
        return

    # Sort log files by modification time (newest first)
    sorted_logs = sorted(log_files, key=os.path.getmtime, reverse=True)

    # Keep only the most recent logs, delete others
    logs_to_delete = sorted_logs[max_logs:]
    for log_file in logs_to_delete:
        try:
            os.remove(log_file)
            print(f"Deleted old log file: {log_file}")
        except Exception as e:
            print(f"Error deleting log file {log_file}: {e}")


def rotate_reports(reports_dir="reports", max_reports=5):
    """
    Rotate HTML report files, keeping only the specified number of most recent reports.

    Args:
        reports_dir (str): Directory containing HTML report files
        max_reports (int): Maximum number of report files to keep
    """
    # Get all HTML report files in the reports directory
    report_files = glob.glob(os.path.join(reports_dir, "options_report_*.html"))

    # If we don't have too many reports yet, no need to delete any
    if len(report_files) <= max_reports:
        return

    # Sort report files by modification time (newest first)
    sorted_reports = sorted(report_files, key=os.path.getmtime, reverse=True)

    # Keep only the most recent reports, delete others
    reports_to_delete = sorted_reports[max_reports:]
    for report_file in reports_to_delete:
        try:
            os.remove(report_file)
            print(f"Deleted old report file: {report_file}")
        except Exception as e:
            print(f"Error deleting report file {report_file}: {e}")


def setup_logging(logs_dir="logs", log_prefix="trader", log_level=logging.DEBUG):
    """
    Set up logging configuration

    Args:
        logs_dir (str): Directory to store log files
        log_prefix (str): Prefix for log filenames
        log_level (int): Logging level

    Returns:
        logger: Configured logger instance
    """
    # Create logs directory if it doesn't exist
    os.makedirs(logs_dir, exist_ok=True)

    # Rotate logs on startup
    rotate_logs(logs_dir=logs_dir, max_logs=5)

    # Set up file handler for all logs
    log_file = os.path.join(
        logs_dir, f"{log_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)  # Capture all logs in file

    # Set up console handler for important messages only
    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        logging.WARNING
    )  # Only show warnings and errors in console

    # Create formatters
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")

    # Set formatters
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Set ib_insync loggers to WARNING level to reduce noise
    logging.getLogger("ib_insync").setLevel(logging.WARNING)
    logging.getLogger("ib_insync.wrapper").setLevel(logging.WARNING)
    logging.getLogger("ib_insync.client").setLevel(logging.WARNING)
    logging.getLogger("ib_insync.ticker").setLevel(logging.WARNING)

    # Return a logger for the calling module
    return logging.getLogger("autotrader")


def get_closest_friday():
    """
    Get the closest Friday from today

    Returns:
        datetime.date: Date of the closest Friday
    """
    today = datetime.now().date()

    # Get the day of the week (0 is Monday, 4 is Friday)
    weekday = today.weekday()

    # Calculate days until Friday
    if weekday < 4:  # Monday to Thursday
        days_to_add = 4 - weekday
    elif weekday == 4:  # Friday
        days_to_add = 0
    else:  # Weekend
        days_to_add = (4 - weekday) % 7  # Next Friday

    closest_friday = today + timedelta(days=days_to_add)
    return closest_friday


def get_next_monthly_expiration():
    """
    Get the next monthly options expiration date (3rd Friday of the month)

    Returns:
        str: Next monthly expiration date in YYYYMMDD format
    """
    today = datetime.now().date()

    # Start with the current month
    year = today.year
    month = today.month

    # Find the first day of the month
    first_day = datetime(year, month, 1).date()

    # Find the first Friday of the month
    weekday = first_day.weekday()
    if weekday < 4:  # Monday to Thursday
        days_to_add = 4 - weekday
    else:  # Friday to Sunday
        days_to_add = (4 - weekday) % 7

    first_friday = first_day + timedelta(days=days_to_add)

    # The third Friday is 14 days after the first Friday
    third_friday = first_friday + timedelta(days=14)

    # If the third Friday is in the past, move to next month
    if third_friday < today:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

        first_day = datetime(year, month, 1).date()

        # Find the first Friday of the next month
        weekday = first_day.weekday()
        if weekday < 4:  # Monday to Thursday
            days_to_add = 4 - weekday
        else:  # Friday to Sunday
            days_to_add = (4 - weekday) % 7

        first_friday = first_day + timedelta(days=days_to_add)
        third_friday = first_friday + timedelta(days=14)

    # Format as YYYYMMDD
    return third_friday.strftime("%Y%m%d")


def parse_date_string(date_str):
    """
    Parse a date string in YYYYMMDD format

    Args:
        date_str (str): Date string in YYYYMMDD format

    Returns:
        datetime: Datetime object
    """
    return datetime.strptime(date_str, "%Y%m%d")


def format_date_string(date_obj):
    """
    Format a datetime object as YYYYMMDD

    Args:
        date_obj (datetime): Datetime object

    Returns:
        str: Date string in YYYYMMDD format
    """
    return date_obj.strftime("%Y%m%d")


def format_currency(value):
    """Format a value as currency"""
    if value is None or isinstance(value, float) and math.isnan(value):
        return "$0.00"
    return f"${value:.2f}"


def format_percentage(value):
    """Format a value as percentage"""
    if value is None or isinstance(value, float) and math.isnan(value):
        return "0.00%"
    return f"{value:.2f}%"


def get_strikes_around_price(price, interval, num_strikes):
    """
    Generate a list of strikes around a given price with specific interval

    Args:
        price (float): The current price
        interval (float): Strike price interval
        num_strikes (int): Number of strikes to generate (half above, half below)

    Returns:
        list: List of strike prices
    """
    strikes = []

    # Find the nearest strike below the current price
    nearest_strike_below = math.floor(price / interval) * interval

    # Generate strikes below the price
    for i in range(num_strikes // 2, 0, -1):
        strikes.append(nearest_strike_below - (i * interval))

    # Add the nearest strike below
    strikes.append(nearest_strike_below)

    # Generate strikes above the price
    for i in range(1, num_strikes // 2 + 1):
        strikes.append(nearest_strike_below + (i * interval))

    return strikes


def is_market_hours(include_after_hours=False):
    """
    Check if the current time is within market hours.

    Standard market hours are 9:30 AM to 4:00 PM ET, Monday to Friday.
    After hours trading is from 4:00 PM to 8:00 PM ET.
    Pre-market trading is from 4:00 AM to 9:30 AM ET.

    Args:
        include_after_hours (bool): Whether to consider after-hours and pre-market as market hours

    Returns:
        bool: True if it's currently market hours, False otherwise

    Examples:
        >>> # Check if it's regular market hours
        >>> is_market_hours()
        True

        >>> # Check if it's regular market hours or extended hours
        >>> is_market_hours(include_after_hours=True)
        True
    """
    # Get the current time in ET
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern)

    # Check if it's a weekend
    if now.weekday() >= 5:  # 5 is Saturday, 6 is Sunday
        return False

    # Current time
    current_time = now.time()

    # Regular market hours check (9:30 AM to 4:00 PM ET)
    market_open = datetime_time(9, 30)
    market_close = datetime_time(16, 0)

    # Regular market hours
    if market_open <= current_time <= market_close:
        return True

    # If we're not including after-hours, then we're done
    if not include_after_hours:
        return False

    # Extended hours check
    pre_market_open = datetime_time(4, 0)
    after_hours_close = datetime_time(20, 0)

    # Pre-market (4:00 AM - 9:30 AM ET)
    if pre_market_open <= current_time < market_open:
        return True

    # After-hours (4:00 PM - 8:00 PM ET)
    if market_close < current_time <= after_hours_close:
        return True

    # Not market hours
    return False
