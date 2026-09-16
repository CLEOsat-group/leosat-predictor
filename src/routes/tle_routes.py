from flask import Blueprint, jsonify, request

from src.services.tle_service import TleService

tle_bp = Blueprint('tle', __name__)
tle_service = TleService()


@tle_bp.route('/predict_course', methods=['POST'])
def predict_course():
    """
    Deprecated: this endpoint never performed a prediction. Use /api/predict.
    """
    return jsonify({
        "error": "unsupported_endpoint",
        "message": "POST /api/predict_course is deprecated and does not perform a prediction. Use POST /api/predict instead.",
        "status": "unsupported",
        "supported_alternative": "/api/predict",
    }), 410

@tle_bp.route('/predict_precise', methods=['POST'])
def predict_precise():
    """
    Deprecated: this endpoint never performed a prediction. Use /api/predict.
    """
    return jsonify({
        "error": "unsupported_endpoint",
        "message": "POST /api/predict_precise is deprecated and does not perform a prediction. Use POST /api/predict instead.",
        "status": "unsupported",
        "supported_alternative": "/api/predict",
    }), 410

@tle_bp.route('/get_constellations', methods=['GET'])
def get_constellations():
    """
    Retrieve the list of constellations from the configuration.
    """
    try:
        constellations = tle_service.list_constellations()
        return jsonify({"constellations": constellations}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to load constellations: {str(e)}"}), 500

@tle_bp.route('/fetch_tle_for_constellation', methods=['GET'])
def fetch_tle_for_constellation():
    """
    Fetch satellites for a constellation, downloading TLEs if expired or forced.
    """
    constellation = request.args.get('constellation', '')
    force_download = request.args.get('force', 'false').lower() == 'true'
    default_only = request.args.get('default_only', 'false').lower() == 'true'  # Parse the toggle state

    if not constellation:
        return jsonify({"error": "Constellation parameter is required."}), 400

    try:
        satellites, cached_file = tle_service.fetch_or_load_constellation(
            constellation,
            force_download=force_download,
            default_only=default_only,
        )
        return jsonify({"satellites": satellites, "source_file": str(cached_file)})

    except Exception as e:
        return jsonify({"error": f"Error handling TLEs for {constellation}: {str(e)}"}), 500

@tle_bp.route('/get_satellite_tle', methods=['GET'])
def get_satellite_tle():
    """
    Fetch TLE data for a specific satellite from a constellation.
    """
    try:
        constellation = request.args.get('constellation', '')
        satellite_name = request.args.get('satellite', '')

        if not constellation or not satellite_name:
            return jsonify({"error": "Both constellation and satellite parameters are required."}), 400

        satellite = tle_service.get_satellite_tle(constellation, satellite_name)
        if satellite is None:
            cached_file = tle_service.get_cached_tle_file(constellation)
            if cached_file is None:
                return jsonify({"error": f"No cached TLE data for constellation {constellation}."}), 404
            return jsonify({"error": f"Satellite {satellite_name} not found in constellation {constellation}."}), 404

        return jsonify({"tle1": satellite["tle1"], "tle2": satellite["tle2"]})
    except Exception as e:
        print(f"Error fetching TLE for satellite {satellite_name} in constellation {constellation}: {e}")
        return jsonify({"error": str(e)}), 500
