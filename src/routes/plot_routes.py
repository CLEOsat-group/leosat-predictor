from flask import Blueprint, jsonify, request
import pandas as pd
import logging

plot_bp = Blueprint('plot', __name__)
logger = logging.getLogger(__name__)


@plot_bp.route('/plot/elevation', methods=['POST'])
def plot_elevation():
    """Endpoint to return elevation vs time plot data."""
    try:
        data = request.json
        task_id = data.get('task_id')

        # Fetch results directly
        results = pd.read_csv(f'data/{task_id}_results.csv')
        results = results[['Obs_Time', 'SatElev']].rename(columns={'Obs_Time': 'time_utc', 'SatElev': 'elevation'})

        return jsonify(results.to_dict(orient='records'))
    except Exception as e:
        logger.error(f"Error generating elevation plot: {e}")
        return jsonify({"error": "Failed to generate plot data"}), 500


@plot_bp.route('/plot/map', methods=['POST'])
def plot_map():
    """Endpoint to return satellite path map data."""
    try:
        data = request.json
        task_id = data.get('task_id')

        # Fetch results directly
        results = pd.read_csv(f'data/{task_id}_results.csv')
        results = results[['SatLat', 'SatLon', 'Obs_Time']].rename(
            columns={'SatLat': 'latitude', 'SatLon': 'longitude', 'Obs_Time': 'time_utc'})

        return jsonify(results.to_dict(orient='records'))
    except Exception as e:
        logger.error(f"Error generating map plot: {e}")
        return jsonify({"error": "Failed to generate map plot data"}), 500
