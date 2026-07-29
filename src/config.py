import os
import json
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

CONFIG_PATH = "config/config.json"
USER_PREFERENCES_PATH = "data/user_preferences.json"


class Config:
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self._config_data = self._load_config()

    def _load_config(self):
        """Load configuration from a JSON file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error loading config file: {e}. Using default values.")
        return {}

    def get(self, key, default=None):
        """Retrieve a configuration value."""
        return self._config_data.get(key, default)

    def set(self, key, value):
        """Set a configuration value."""
        self._config_data[key] = value
        self._save_config()

    def get_all(self):
        """Retrieve all configuration values."""
        return self._config_data

    def _save_config(self):
        """Save the current configuration to the JSON file."""
        try:
            with open(self.config_path, "w") as f:
                json.dump(self._config_data, f, indent=4)
        except IOError as e:
            print(f"Error saving config file: {e}")


# Initialize Config for user_preferences.json
class UserPreferences(Config):
    def __init__(self):
        super().__init__(config_path=USER_PREFERENCES_PATH)
