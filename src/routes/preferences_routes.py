from flask import Blueprint, jsonify, request
from src.config import Config, UserPreferences

preferences_bp = Blueprint('preferences', __name__)

CONFIG = Config()
USER_PREFERENCES = UserPreferences()


@preferences_bp.route('/get_default_preferences', methods=['GET'])
def get_default_preferences():
    """
    Fetch preferences from user_preferences.json with fallback to config.json.
    """
    try:
        preferences = USER_PREFERENCES.get_all()
        if not preferences:
            preferences = CONFIG.get_all()
            USER_PREFERENCES.set("default_location", preferences.get("default_location", {}))
            USER_PREFERENCES.set("tle_expiration_hours", preferences.get("tle_expiration_hours", 24))

        return jsonify(preferences), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@preferences_bp.route('/save_preferences', methods=['POST'])
def save_preferences():
    """
    Save preferences to user_preferences.json.
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided."}), 400

        for key, value in data.items():
            USER_PREFERENCES.set(key, value)

        return jsonify({"message": "Preferences saved successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
