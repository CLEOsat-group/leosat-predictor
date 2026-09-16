"""HTTP routes for shared observatory catalog and elevation lookup."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models.formatter import get_elevation
from ..services.observatory_catalog import build_observatory_catalog


observatory_bp = Blueprint("observatories", __name__)


@observatory_bp.route("/observatories", methods=["GET"])
def get_observatories():
    """Return the same normalized observatory catalog used by the GUI map."""

    return jsonify(build_observatory_catalog())


@observatory_bp.route("/get_elevation", methods=["GET"])
def fetch_elevation():
    """Return elevation for one latitude/longitude query pair."""

    lat = request.args.get("lat")
    lon = request.args.get("lon")

    if not lat or not lon:
        return jsonify({"error": "Missing latitude or longitude"}), 400

    try:
        elevation = get_elevation(lat, lon)
        return jsonify({"elevation": elevation})
    except Exception as exc:  # pragma: no cover - remote-service failure path
        return jsonify({"error": f"Failed to fetch elevation: {exc}"}), 500
