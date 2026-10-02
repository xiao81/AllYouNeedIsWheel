"""
Centralized logging configuration module for the Auto-Trader application
"""

import os
import logging
import glob
from datetime import datetime

# Base directory for logs
LOGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)

# Ensure log directories exist
for subdir in ["api", "tws", "server", "general"]:
    os.makedirs(os.path.join(LOGS_DIR, subdir), exist_ok=True)

# Log file name format with timestamp
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def get_log_path(log_type):
    """Get the path for a specific log type with timestamp"""
    return os.path.join(LOGS_DIR, log_type, f"{log_type}_{TIMESTAMP}.log")


def cleanup_old_logs(log_type, max_logs=5):
    """
    Cleanup old log files, keeping only the latest N logs

    Args:
        log_type (str): Type of log ('api', 'tws', 'server', 'general')
        max_logs (int): Number of log files to keep (default: 5)
    """
    log_dir = os.path.join(LOGS_DIR, log_type)
    log_pattern = os.path.join(log_dir, f"{log_type}_*.log")

    # Get all log files for this type
    log_files = glob.glob(log_pattern)

    # If we have more logs than the maximum, remove the oldest ones
    if len(log_files) > max_logs:
        # Sort by modification time (newest first)
        log_files.sort(key=os.path.getmtime, reverse=True)

        # Remove older logs (keep the newest max_logs)
        for old_log in log_files[max_logs:]:
            try:
                os.remove(old_log)
                print(f"Removed old log file: {old_log}")
            except Exception as e:
                print(f"Error removing log file {old_log}: {e}")


def configure_logging(
    module_name, log_type=None, console_level=logging.INFO, file_level=logging.DEBUG
):
    """
    Configure logging for a module

    Args:
        module_name (str): Name of the module (used as logger name)
        log_type (str, optional): Type of log ('api', 'tws', 'server', or None for 'general')
        console_level (int, optional): Logging level for console output. Defaults to logging.INFO.
        file_level (int, optional): Logging level for file output. Defaults to logging.DEBUG.

    Returns:
        logging.Logger: Configured logger
    """
    # Determine log type directory
    if not log_type:
        log_type = "general"

    # First, clean up old logs to maintain only max_logs=5
    cleanup_old_logs(log_type, max_logs=5)

    # Create logger
    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)  # Capture all levels

    # Remove existing handlers if any
    if logger.handlers:
        logger.handlers = []

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    )
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler - we create a new timestamped file for each run
    # but limit the total number of log files
    log_file = get_log_path(log_type)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(file_level)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)

    # Log startup information
    logger.info(f"Logging initialized for {module_name} to {log_file}")

    return logger


def get_logger(module_name, log_type=None):
    """
    Get a configured logger for a module

    Args:
        module_name (str): Name of the module
        log_type (str, optional): Type of log ('api', 'tws', 'server', or None for 'general')

    Returns:
        logging.Logger: Configured logger
    """
    return configure_logging(module_name, log_type)
