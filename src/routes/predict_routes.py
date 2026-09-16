# src/routes/predict_routes.py
import logging
import time
from datetime import datetime

import pandas as pd
from astropy.coordinates import EarthLocation
from dateutil.parser import parse as parse_date
from flask import Blueprint, jsonify, Response, stream_with_context, send_file, request
import gzip
from pathlib import Path
import io
import csv
import json

from src.prediction_core.precise_materialization import (
    COLUMN_ORDER_PRECISE,
    COLUMN_ORDER_PRECISE_BASE,
    COLUMN_ORDER_PRECISE_EXPORT,
    COLUMN_ORDER_PRECISE_WITH_PHASE,
    COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE,
    COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE_AND_LABELS,
    infer_precise_column_order,
)
from src.services.results_handler import ResultsHandler
from src.utils.results_processor import process_results
from src.utils.time_utils import calculate_timezone_offset, get_date_time_object

# Helpers for pointer file streaming (from our redis_task_store)
from src.web import redis_task_store as rts
from src.web.prediction_manager_web import prediction_manager

# Instantiate ResultsHandler for database operations
results_handler = ResultsHandler()

# Logging setup
logger = logging.getLogger(__name__)

# Flask Blueprint
predict_bp = Blueprint('predict', __name__)

# Public/default CSV export adds the scientific SolarPhaseAngle field while
# keeping internal twilight labels out of CSV by default.
COLUMN_ORDER_PRECISE_CSV = COLUMN_ORDER_PRECISE_EXPORT

COLUMN_ORDER_OVERPASS = ['Sat_ID', 'rise_time_loc', 'max_time_loc', 'set_time_loc', 'rise_time_utc', 'max_time_utc',
                         'set_time_utc', 'rise_azimuth', 'max_elevation', 'set_azimuth',
                         'SatAzRise', 'SatElevRise', 'SatAltRise', 'SatDistRise', 'SatLonRise', 'SatLatRise',
                         'SatAz', 'SatElev', 'SatAlt', 'SatDist', 'SatLon', 'SatLat',
                         'SatAzSet', 'SatElevSet', 'SatAltSet', 'SatDistSet', 'SatLonSet', 'SatLatSet',
                         'SunRA', 'SunDEC']


def _precise_columns_for_dict(record):
    """Infer the precise contract represented by a dict row."""
    if {"SolarPhaseAngle", "time_of_day", "light_phase"}.issubset(record):
        return COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE_AND_LABELS
    if {"time_of_day", "light_phase"}.issubset(record):
        return COLUMN_ORDER_PRECISE_WITH_PHASE
    if "SolarPhaseAngle" in record:
        return COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE
    return COLUMN_ORDER_PRECISE_BASE


def _unsupported_precise_width_message(row_width):
    """Return a consistent error for unsupported precise row widths."""
    return (
        f"Unsupported precise row width: {row_width}. "
        "Expected 18 legacy columns, 20 Task-25 label columns, "
        "or 21 current columns."
    )


@predict_bp.route('/predict', methods=['POST'])
def predict():
    """
    Start a prediction task (unchanged semantics) — returns task_id immediately.
    """
    try:
        data = request.json
        logger.info("Received prediction request payload")

        satellites_list = data.get('satellites', [])
        if not satellites_list:
            return jsonify({"error": "No satellites selected."}), 400

        lat = float(data['lat'])
        lon = float(data['lon'])
        alt = float(data.get('observer_alt', 0.0))
        name = data.get('location_name', "No Name")
        location = {"name": name, "lat": lat, "lon": lon, "alt": alt}

        mode = data.get('mode', 'precise')
        days_to_predict = int(data.get('days', 1))
        prediction_range_overpass = data.get('prediction_range_overpass', 'night').lower()
        prediction_range_precise = data.get('prediction_range_precise', 'both').lower()
        interval = int(data.get('interval', 300))
        interval_unit = data.get('interval_unit', 'seconds')
        margin = int(data.get("margin", 5))

        raw_constraints = data.get('constraints', {}) or {}
        constraints = {
            "mode": mode,
            "location": location,
            "prediction_range_overpass": prediction_range_overpass,
            "lowest_altitude_satellite": float(raw_constraints.get('lowest_altitude_satellite', 0)),
            "sun_zenith_highest": float(raw_constraints.get('sun_zenith_highest', 180)),
            "sun_zenith_lowest": float(raw_constraints.get('sun_zenith_lowest', 0)),
        }

        if interval_unit == 'minutes':
            interval *= 60
        elif interval_unit == 'hours':
            interval *= 3600

        start_date = data.get('start_date', datetime.now().isoformat())
        parsed_date = parse_date(start_date)
        parsed_date = datetime.strptime(parsed_date.strftime('%Y-%m-%dT%H:%M'), '%Y-%m-%dT%H:%M')

        if mode == "precise":
            timezone_offset = calculate_timezone_offset()
            time_params = {
                "year": parsed_date.year,
                "month": parsed_date.month,
                "day": parsed_date.day,
                "window": prediction_range_precise,
            }
            start_datetime, end_datetime = get_date_time_object(time_params, timezone_offset)
        else:
            start_datetime = parsed_date.isoformat()
            end_datetime = None

        task_id = prediction_manager.start_task(
            mode=mode,
            satellites=satellites_list,
            location=location,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            days=days_to_predict,
            interval=interval,
            margin=margin,
            constraints=constraints
        )

        return jsonify({"task_id": task_id, "status": "started"}), 202

    except KeyError as e:
        return jsonify({"error": f"Missing parameter: {str(e)}"}), 400
    except ValueError as e:
        return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
    except Exception as e:
        logger.exception("Failed to start prediction: %s", e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


@predict_bp.route('/cancel_prediction', methods=['POST'])
def cancel_prediction():
    try:
        data = request.json or {}
        task_id = data.get("task_id")
        if not task_id:
            return jsonify({"error": "No task_id provided"}), 400

        logger.info("Canceling task with ID: %s", task_id)
        status = prediction_manager.get_status(task_id)
        if status == "unknown":
            return jsonify({"error": f"Task {task_id} not found"}), 404

        prediction_manager.cancel_task(task_id)
        return jsonify({"status": "cancelled"}), 200

    except Exception as e:
        logger.exception("Cancel failed: %s", e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


@predict_bp.route('/task_status/<string:task_id>', methods=['GET'])
def task_status(task_id):
    try:
        status = prediction_manager.get_status(task_id)
        logger.info("Task %s status retrieved: %s", task_id, status)
        return jsonify({"task_id": task_id, "status": status}), 200
    except Exception as e:
        logger.exception("Error retrieving status: %s", e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500



def _precise_columns_for_rows(rows):
    """Return the precise column contract for the first raw precise row found."""
    for row in rows or []:
        if isinstance(row, (list, tuple)):
            columns = infer_precise_column_order(row)
            if columns is None:
                raise ValueError(_unsupported_precise_width_message(len(row)))
            return columns
        if isinstance(row, dict):
            return _precise_columns_for_dict(row)
    return COLUMN_ORDER_PRECISE


def _precise_export_columns_for_rows(rows):
    """Return the public/default precise CSV export columns after validation.

    New precise materialization rows contain the public ``SolarPhaseAngle``
    field plus internal ``time_of_day`` and ``light_phase`` fields. CSV export
    includes ``SolarPhaseAngle`` and excludes the internal labels, while this
    helper still validates that raw list rows follow a known precise contract.
    """
    _precise_columns_for_rows(rows)
    return COLUMN_ORDER_PRECISE_CSV


def _columns_for_record(rec, mode, *, for_export=False):
    """Infer materialization or CSV-export columns for one record."""
    if mode != "precise":
        return COLUMN_ORDER_OVERPASS

    if for_export:
        if isinstance(rec, (list, tuple)) and infer_precise_column_order(rec) is None:
            raise ValueError(_unsupported_precise_width_message(len(rec)))
        return COLUMN_ORDER_PRECISE_CSV

    if isinstance(rec, dict):
        return _precise_columns_for_dict(rec)
    if isinstance(rec, (list, tuple)):
        columns = infer_precise_column_order(rec)
        if columns is not None:
            return columns
        raise ValueError(_unsupported_precise_width_message(len(rec)))
    return COLUMN_ORDER_PRECISE


def _row_for_columns(rec, columns, mode=None):
    """Normalize a dict/list record to a CSV row following ``columns``.

    Precise list rows must be mapped through their inferred source contract
    before public export projection.  This prevents legacy 20-column rows from
    being mis-exported with ``time_of_day`` in the new ``SolarPhaseAngle`` slot.
    """
    if isinstance(rec, dict):
        return [rec.get(column, "") for column in columns]
    if isinstance(rec, (list, tuple)) and mode == "precise":
        source_columns = infer_precise_column_order(rec)
        if source_columns is None:
            raise ValueError(_unsupported_precise_width_message(len(rec)))
        rec_obj = dict(zip(source_columns, rec))
        return [rec_obj.get(column, "") for column in columns]
    return [rec[index] if index < len(rec) else "" for index, _ in enumerate(columns)]


def _materialize_record_to_dict(rec, mode):
    """Convert a raw pointer/inline record to a dict keyed by known columns."""
    if isinstance(rec, dict):
        return rec
    if not isinstance(rec, (list, tuple)):
        return {"raw": str(rec)}

    if mode == "precise":
        cols = infer_precise_column_order(rec)
        if cols is None:
            raise ValueError(_unsupported_precise_width_message(len(rec)))
    else:
        cols = COLUMN_ORDER_OVERPASS

    if len(rec) != len(cols):
        raise ValueError(
            f"Unsupported {mode} row width: {len(rec)}. Expected {len(cols)} columns."
        )
    return dict(zip(cols, rec))



@predict_bp.route('/get_results/<string:task_id>', methods=['GET'])
def get_results(task_id):
    """
    Primary results endpoint. Behavior:
     - If processed results stored in DB -> return full processed rows (fast).
     - Otherwise wait for prediction_manager to finish (small poll).
     - If prediction produced an inline 'results' list -> process (vectorized) and store DB then return full processed rows.
     - If prediction produced a 'pointer' -> return a lightweight aggregate + pointer immediately (fast).
         Client can then call /api/get_results_page to get paged rows, or /api/get_plot to fetch plot data.
    """
    try:
        logger.info("Fetching results for task ID: %s", task_id)

        # 1) If previously stored in DB, return it (fast)
        stored_results = results_handler.fetch_results(str(task_id))
        if stored_results:
            logger.info("Returning stored results for task ID %s.", task_id)
            return jsonify({"status": "completed", "results": stored_results}), 200

        # 2) Wait for completion (bounded)
        wait_start = time.time()
        wait_timeout = 300.0  # 5 min safety; tune as needed
        poll_interval = 0.2

        while True:
            status = prediction_manager.get_status(task_id)
            if status == "completed":
                break
            elif status == "cancelled":
                logger.info("Task %s cancelled.", task_id)
                return jsonify({"status": "cancelled", "results": []}), 200
            elif status == "unknown":
                return jsonify({"error": "Task not found"}), 404

            if time.time() - wait_start > wait_timeout:
                logger.warning("Timeout waiting for task %s to finish.", task_id)
                return jsonify({"status": "running", "message": "Task still running, try again later."}), 202
            time.sleep(poll_interval)

        # 3) Get persisted payload (may be inline results or pointer)
        payload = prediction_manager.get_results(task_id)
        if not payload:
            return jsonify({"error": "No results found."}), 500

        # if the worker returned an error object
        if isinstance(payload, dict) and payload.get("status") in ("error",) and payload.get("results"):
            return jsonify(payload), 500

        # Inline results (small-ish): process here and store final processed form in DB
        if "results" in payload and isinstance(payload["results"], list):
            raw_list = payload["results"]
            logger.info("Inline results returned (count=%d) for task %s", len(raw_list), task_id)

            constraints = prediction_manager.get_constraints(task_id) or {}
            mode = constraints.get("mode", "precise")
            loc = constraints.get("location", {}) or {}
            lat = loc.get("lat")
            lon = loc.get("lon")
            alt = loc.get("alt")
            loc_name = loc.get("name", "")

            # Build DataFrame and process in parent thread (astropy vectorized work allowed).
            # Precise rows may be legacy 18-column rows or current 20-column rows.
            if mode == "precise":
                df = pd.DataFrame(raw_list, columns=_precise_columns_for_rows(raw_list))
            else:
                df = pd.DataFrame(raw_list, columns=COLUMN_ORDER_OVERPASS)

            processed_df = process_results(results=df, mode=mode, constraints=constraints,
                                           location=EarthLocation(lat=lat, lon=lon, height=alt))
            if processed_df is None:
                processed_df = df

            # Store processed results in DB for fast subsequent reads
            results_handler.store_results(
                task_id=str(task_id),
                mode=mode,
                observer_lat=lat,
                observer_lon=lon,
                observer_alt=alt,
                observer_name=loc_name,
                results=processed_df.to_dict(orient="records")
            )
            return jsonify({"status": "completed", "results": processed_df.to_dict(orient="records")}), 200

        # Pointer case: return the lightweight payload immediately.
        # The client (main.js) knows how to use "pointer" + "aggregate" to fetch pages or plots.
        if "pointer" in payload:
            logger.info("Returning pointer payload for task %s (no server-side materialization)", task_id)
            # Ensure aggregate is present if possible (lazy compute if missing?)
            # Usually manager computes it. If not, client handles it.
            return jsonify(payload), 200

        # Fallback: unknown payload shape
        return jsonify({"status": payload.get("status", "completed"), "results": payload.get("results", [])}), 200

    except Exception as e:
        logger.exception("Error retrieving results for %s: %s", task_id, e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


@predict_bp.route('/get_results_page/<string:task_id>', methods=['GET'])
def get_results_page(task_id):
    """
    Return a single page of results for the task. Query params:
      - page (1-indexed)
      - limit (rows per page)
    Behavior:
      - If processed DB entry exists, serve page from DB.
      - Else if pointer exists, stream pointer, skip offset and return only requested page (low-memory).
      - Else if inline payload exists (but not yet stored), slice the inline list.
    """
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 200))
        if page < 1:
            page = 1
        offset = (page - 1) * limit

        # If DB materialized, read page from DB
        stored_results = results_handler.fetch_results(str(task_id))
        if stored_results:
            df = pd.DataFrame(stored_results)
            start = offset
            end = offset + limit
            page_slice = df.iloc[start:end].to_dict(orient="records")
            return jsonify({"status": "completed", "page": page, "limit": limit, "rows": page_slice}), 200

        # Else check persisted payload (pointer or inline) in Redis
        payload = prediction_manager.get_results(task_id)
        if not payload:
            return jsonify({"error": "No results available"}), 404

        # Inline results present
        if "results" in payload and isinstance(payload["results"], list):
            raw = payload["results"]
            slice_rows = raw[offset:offset + limit]
            # convert records to dicts based on mode
            constraints = prediction_manager.get_constraints(task_id) or {}
            mode = constraints.get("mode", "precise")
            rows = [_materialize_record_to_dict(rec, mode) for rec in slice_rows]
            return jsonify({"status": "completed", "page": page, "limit": limit, "rows": rows}), 200

        # Pointer case: stream the gzipped NDJSON and skip/collect
        if "pointer" in payload:
            pointer = payload["pointer"]
            # rts.load_results_from_pointer yields raw JSON-decoded records
            it = rts.load_results_from_pointer(pointer)
            collected = []
            skipped = 0
            # skip until offset, then collect limit items
            for rec in it:
                if skipped < offset:
                    skipped += 1
                    continue
                collected.append(rec)
                if len(collected) >= limit:
                    break
            # Convert to dicts with column names
            constraints = prediction_manager.get_constraints(task_id) or {}
            mode = constraints.get("mode", "precise")
            rows = [_materialize_record_to_dict(r, mode) for r in collected]
            return jsonify({"status": "completed", "page": page, "limit": limit, "rows": rows}), 200

        return jsonify({"error": "Unsupported result payload"}), 500

    except Exception as e:
        logger.exception("get_results_page failed for %s: %s", task_id, e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@predict_bp.route('/download_results/<string:task_id>', methods=['GET'])
def download_results(task_id):
    """
    Stream a download for a task:
      - if pointer -> serve the gzipped NDJSON directly when format not csv
      - if pointer && format=csv -> stream convert NDJSON -> CSV using column mapping (mode-aware)
      - if inline results present -> convert them to CSV (format=csv) or JSON otherwise
    """
    try:
        fmt = (request.args.get('format') or 'ndjson').lower()  # 'csv' or 'ndjson' (default ndjson)
        payload = prediction_manager.get_results(task_id)
        if not payload:
            return jsonify({"error": "Results not available"}), 404

        # Inline small results
        if "results" in payload and isinstance(payload["results"], list):
            rows = payload["results"]
            if fmt == 'csv':
                constraints = prediction_manager.get_constraints(task_id) or {}
                mode = constraints.get("mode", "precise")
                cols = _precise_export_columns_for_rows(rows) if mode == "precise" else COLUMN_ORDER_OVERPASS

                def gen_inline_csv():
                    out = io.StringIO()
                    writer = csv.writer(out)
                    writer.writerow(cols)
                    yield out.getvalue()
                    out.seek(0); out.truncate(0)
                    for rec in rows:
                        writer.writerow(_row_for_columns(rec, cols, mode=mode))
                        yield out.getvalue()
                        out.seek(0); out.truncate(0)
                headers = {"Content-Disposition": f'attachment; filename="{task_id}.csv"'}
                return Response(stream_with_context(gen_inline_csv()), mimetype='text/csv', headers=headers)

            # default: return JSON with inline results
            return jsonify({"status": "completed", "results": rows}), 200

        # Pointer case: file://...
        if "pointer" in payload:
            pointer = payload["pointer"]
            if not pointer.startswith("file://"):
                return jsonify({"error": "Unsupported pointer scheme"}), 500
            path = pointer[len("file://"):]
            p = Path(path)
            if not p.exists():
                return jsonify({"error": "Pointer file not found on server"}), 404

            # If user asked for raw ndjson (or default), just send the gz file
            if fmt != 'csv':
                # Stream the gz file as-is
                return send_file(str(p.resolve()), as_attachment=True, download_name=f"{task_id}.ndjson.gz")

            # If format=csv, stream-convert NDJSON gz -> CSV.
            constraints = prediction_manager.get_constraints(task_id) or {}
            mode = constraints.get("mode", "precise")

            def gen_csv_from_gz():
                out = io.StringIO()
                writer = csv.writer(out)
                wrote_header = False

                with gzip.open(str(p.resolve()), "rt", encoding="utf-8") as gz:
                    for line in gz:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue

                        if not wrote_header:
                            cols = _columns_for_record(rec, mode, for_export=True)
                            writer.writerow(cols)
                            yield out.getvalue()
                            out.seek(0); out.truncate(0)
                            wrote_header = True

                        writer.writerow(_row_for_columns(rec, cols, mode=mode))
                        yield out.getvalue()
                        out.seek(0); out.truncate(0)

                if not wrote_header:
                    cols = COLUMN_ORDER_PRECISE_CSV if mode == "precise" else COLUMN_ORDER_OVERPASS
                    writer.writerow(cols)
                    yield out.getvalue()
                    out.seek(0); out.truncate(0)

            headers = {"Content-Disposition": f'attachment; filename="{task_id}.csv"'}
            return Response(stream_with_context(gen_csv_from_gz()), mimetype='text/csv', headers=headers)

        return jsonify({"error": "Unsupported payload for download"}), 500

    except Exception as e:
        logger.exception("download_results failed: %s", e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@predict_bp.route('/get_plot/<string:task_id>', methods=['GET'])
def get_plot(task_id):
    """
    Lightweight plot endpoint:
      - If processed DB entry exists, compute quick aggregates and return.
      - Else if pointer exists, stream once and return aggregated summary (very cheap).
    This is what the UI should call to render plots quickly.
    """
    try:
        # try DB first
        stored = results_handler.fetch_results(str(task_id))
        if stored:
            df = pd.DataFrame(stored)
            if df.empty:
                return jsonify({"status": "completed", "plot": {}}), 200

            # Determine time column
            time_col = "Obs_Time" if "Obs_Time" in df.columns else ("max_time_utc" if "max_time_utc" in df.columns else None)
            if time_col:
                df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
                agg = df.groupby("Sat_ID").agg(samples=("Sat_ID", "count"),
                                              t_min=(time_col, "min"),
                                              t_max=(time_col, "max")).reset_index()
                agg["t_min"] = agg["t_min"].dt.strftime("%Y-%m-%dT%H:%M:%S")
                agg["t_max"] = agg["t_max"].dt.strftime("%Y-%m-%dT%H:%M:%S")
                return jsonify({"status": "completed", "plot": agg.to_dict(orient="records")}), 200

            # fallback: simple counts
            counts = df["Sat_ID"].value_counts().to_dict()
            return jsonify({"status": "completed", "plot": {"counts": counts}}), 200

        # else check pointer / inline via prediction_manager
        payload = prediction_manager.get_results(task_id)
        if not payload:
            return jsonify({"status": "running", "message": "Results not available yet."}), 202

        if "pointer" in payload:
            try:
                agg = prediction_manager.load_pointer_aggregate(payload)
                return jsonify({"status": "completed", "plot": agg}), 200
            except Exception:
                logger.exception("Pointer aggregate failed for %s", task_id)
                return jsonify({"status": "completed", "plot": {}}), 200

        if "results" in payload and isinstance(payload["results"], list):
            # small inline results
            raw = payload["results"]
            df = pd.DataFrame(raw)
            if df.empty:
                return jsonify({"status": "completed", "plot": {}}), 200
            # choose time column heuristically
            time_col = "Obs_Time" if "Obs_Time" in df.columns else ("max_time_utc" if "max_time_utc" in df.columns else None)
            if time_col:
                df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
                agg = df.groupby(0 if 0 in df.columns else "Sat_ID").agg(samples=(0 if 0 in df.columns else "Sat_ID", "count"),
                                                                         t_min=(time_col, "min"),
                                                                         t_max=(time_col, "max")).reset_index()
                agg["t_min"] = agg["t_min"].dt.strftime("%Y-%m-%dT%H:%M:%S")
                agg["t_max"] = agg["t_max"].dt.strftime("%Y-%m-%dT%H:%M:%S")
                return jsonify({"status": "completed", "plot": agg.to_dict(orient="records")}), 200
            # fallback counts
            return jsonify({"status": "completed", "plot": {"count": len(raw)}}), 200

        return jsonify({"error": "Unsupported payload"}), 500

    except Exception as e:
        logger.exception("get_plot failed for %s: %s", task_id, e)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
