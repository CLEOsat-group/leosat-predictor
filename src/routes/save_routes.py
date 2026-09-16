import json
import os

from flask import Blueprint, jsonify, request

save_bp = Blueprint('save', __name__)

USER_PREFERENCES_PATH = "data/user_preferences.json"


def initialize_user_preferences():
    """Ensure user_preferences.json exists, creating it with default structure if necessary."""
    if not os.path.exists(USER_PREFERENCES_PATH):
        with open(USER_PREFERENCES_PATH, 'w') as f:
            json.dump({"default_location": {}}, f, indent=4)


@save_bp.route('/get_default_location', methods=['GET'])
def get_default_location():
    """Fetch the default location from user_preferences.json."""
    try:
        initialize_user_preferences()
        with open(USER_PREFERENCES_PATH, 'r') as f:
            preferences = json.load(f)
        default_location = preferences.get("default_location", {})
        if default_location:
            return jsonify(default_location), 200
        return jsonify({"error": "No default location found."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@save_bp.route('/save_default_location', methods=['POST'])
def save_default_location():
    """Save the default location to user_preferences.json."""
    try:
        data = request.json
        if not all(key in data for key in ["name", "latitude", "longitude", "altitude"]):
            return jsonify({"error": "Invalid location data."}), 400

        initialize_user_preferences()
        with open(USER_PREFERENCES_PATH, 'r+') as f:
            preferences = json.load(f)
            preferences["default_location"] = {
                "name": data["name"],
                "latitude": float(data["latitude"]),
                "longitude": float(data["longitude"]),
                "altitude": float(data["altitude"]),
            }
            f.seek(0)
            json.dump(preferences, f, indent=4)
            f.truncate()

        return jsonify({"message": "Default location saved successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
