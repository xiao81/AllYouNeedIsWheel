import os
import json
import logging

logger = logging.getLogger("autotrader.config")


class Config:
    """
    Configuration class for the AutoTrader application
    """

    def __init__(self, default_config=None, config_file=None):
        """
        Initialize the configuration with default values and load from a file if provided

        Args:
            default_config (dict, optional): Default configuration values. Defaults to None.
            config_file (str, optional): Path to a JSON configuration file. Defaults to None.
        """
        # Initialize with default values
        self.config = default_config.copy() if default_config else {}

        if config_file is None:
            from core.settings import read_profiles, SETTINGS_PATH

            env_path = os.environ.get("CONNECTION_CONFIG")
            if SETTINGS_PATH.exists() or env_path in (
                None,
                "connection.json",
                "connection_real.json",
            ):
                profiles = read_profiles()
                self.config.update(profiles[profiles["mode"]])
                self.config["mode"] = profiles["mode"]
                return
            config_file = env_path
        if config_file and os.path.exists(config_file):
            self.load_from_file(config_file)

    def load_from_file(self, config_file):
        """
        Load configuration from a JSON file

        Args:
            config_file (str): Path to a JSON configuration file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(config_file, "r") as f:
                file_config = json.load(f)

            # Update our configuration with values from the file
            self.config.update(file_config)
            return True
        except Exception as e:
            logger.error(f"Error loading configuration from {config_file}: {str(e)}")
            return False

    def get(self, key, default=None):
        """
        Get a configuration value

        Args:
            key (str): Configuration key
            default: Default value to return if the key is not found

        Returns:
            The configuration value or default
        """
        return self.config.get(key, default)

    def set(self, key, value):
        """
        Set a configuration value

        Args:
            key (str): Configuration key
            value: Value to set
        """
        self.config[key] = value

    def to_dict(self):
        """
        Get the entire configuration as a dictionary

        Returns:
            dict: Configuration dictionary
        """
        return self.config.copy()

    def save_to_file(self, config_file):
        """
        Save the configuration to a JSON file

        Args:
            config_file (str): Path to a JSON configuration file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(config_file, "w") as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Error saving configuration to {config_file}: {str(e)}")
            return False
