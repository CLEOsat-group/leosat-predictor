import json
import sqlite3
import csv
import io
import os
from typing import Iterable, List, Dict, Any, Optional

from flask import jsonify, stream_with_context, Response

from src.models.database import initialize_database
from src.prediction_core.precise_materialization import COLUMN_ORDER_PRECISE_EXPORT


DEFAULT_DB_PATH = "data/satellite_data.db"
BATCH_INSERT_SIZE = 1000  # tune this for your environment


class ResultsHandler:
    """Handles dataset operations for the web interface and DB persistence.

    Responsibilities:
      - Ensure DB/schema exists
      - Store canonical JSON results (prediction_results)
      - Optionally normalize & bulk-insert row-level data into prediction_rows
      - Provide a streaming CSV download for a task_id
    """

    # exact columns in prediction_rows table we will attempt to populate
    PRED_ROWS_COLUMNS = [
        "task_id", "mode", "Sat_ID", "Obs_Time", "Local_Time", "UT_Date", "UT_time",
        "SatRA", "SatDEC", "SatAz", "SatElev", "SolarPhaseAngle", "SatAlt", "SatDist",
        "SunRA", "SunDEC", "SunZenithAngle", "RA", "DEC", "SatLon", "SatLat",
        "rise_time_loc", "max_time_loc", "set_time_loc",
        "rise_time_utc", "max_time_utc", "set_time_utc",
        "rise_azimuth", "max_elevation", "set_azimuth",
        "SatAzRise", "SatElevRise", "SatAltRise", "SatDistRise", "SatLonRise", "SatLatRise",
        "SatAzSet", "SatElevSet", "SatAltSet", "SatDistSet", "SatLonSet", "SatLatSet",
        "time_of_day", "light_phase"
    ]

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        initialize_database(db_path)
        self.db_path = db_path

    #
    # Lightweight getters (unchanged behavior)
    #
    def get_data(self, dataset_name, start=0, limit=50, as_json=False):
        conn = sqlite3.connect(self.db_path)
        query = f"SELECT * FROM {dataset_name} LIMIT ? OFFSET ?"
        df = None
        try:
            import pandas as pd
            df = pd.read_sql_query(query, conn, params=(limit, start))
        finally:
            conn.close()

        if as_json:
            return jsonify({"data": df.to_dict(orient="records"), "total": len(df)})
        return df

    def filter_data(self, mode, task_id=None, filters=None, as_json=False):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT observer_lat, observer_lon, observer_alt, observer_name, results 
            FROM prediction_results 
            WHERE task_id = ?
        """, (task_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return jsonify([]) if as_json else __import__("pandas").DataFrame()

        observer_lat, observer_lon, observer_alt, observer_name, results_json = row
        results = json.loads(results_json)
        df = __import__("pandas").DataFrame(results)

        if mode == "overpass":
            df["max_time_loc_formatted"] = __import__("pandas").to_datetime(df["max_time_loc"]).dt.strftime('%Y-%m-%d')
        else:
            df["Obs_Time_formatted"] = __import__("pandas").to_datetime(df["Obs_Time"]).dt.strftime('%Y-%m-%d')

        if filters:
            if "Sat_ID" in filters and filters["Sat_ID"]:
                df = df[df["Sat_ID"].isin(filters["Sat_ID"])]
            if "time_of_day" in filters and filters["time_of_day"]:
                df = df[df["time_of_day"].isin(filters["time_of_day"])]
            if "min_elevation" in filters and filters["min_elevation"] is not None:
                df = df[df["SatElev"] >= float(filters["min_elevation"])]
            if "date_val" in filters and filters["date_val"]:
                date_key = "max_time_loc_formatted" if mode == "overpass" else "Obs_Time_formatted"
                df = df[df[date_key].isin(filters["date_val"])]

        conn.close()

        if as_json:
            return jsonify({
                "data": df.to_dict(orient="records"),
                "observer_lat": observer_lat,
                "observer_lon": observer_lon,
                "observer_alt": observer_alt,
                "observer_name": observer_name,
            })
        return df, observer_lat, observer_lon, observer_alt, observer_name

    #
    # Persist canonical JSON + optional normalized rows in a single transaction.
    #
    def store_results(self,
                      task_id: str,
                      mode: str,
                      observer_lat: float,
                      observer_lon: float,
                      observer_alt: float,
                      observer_name: str,
                      results: List[Dict[str, Any]],
                      also_insert_rows: bool = True) -> None:
        """
        Persist canonical JSON in prediction_results and optionally
        insert per-row entries into prediction_rows for fast server-side filtering and streaming.

        - results is expected to be a list of dict-like objects (typical worker output).
        - If also_insert_rows is True we will try to map dict keys -> prediction_rows columns.
        """
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            cur = conn.cursor()
            # Begin transaction: update canonical JSON then optionally insert rows
            cur.execute("BEGIN IMMEDIATE")

            results_json = json.dumps(results, default=str)
            cur.execute("""
                INSERT INTO prediction_results (task_id, mode, observer_lat, observer_lon, observer_alt, observer_name, results)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                  mode=excluded.mode,
                  observer_lat=excluded.observer_lat,
                  observer_lon=excluded.observer_lon,
                  observer_alt=excluded.observer_alt,
                  observer_name=excluded.observer_name,
                  results=excluded.results
            """, (task_id, mode, observer_lat, observer_lon, observer_alt, observer_name, results_json))

            if also_insert_rows and isinstance(results, list) and len(results) > 0:
                # prepare insert statement and rows in batches
                col_placeholders = ",".join("?" for _ in self.PRED_ROWS_COLUMNS)
                insert_sql = f"INSERT INTO prediction_rows ({', '.join(self.PRED_ROWS_COLUMNS)}) VALUES ({col_placeholders})"
                to_insert = []

                for rec in results:
                    # rec may be dict or list - prefer dict
                    if isinstance(rec, dict):
                        row = [rec.get(col) for col in self.PRED_ROWS_COLUMNS]
                    elif isinstance(rec, (list, tuple)):
                        # if caller returned positional rows, try to map common fields heuristically:
                        # Put task_id and mode first, then fill remaining values with None if short.
                        row = [task_id, mode] + list(rec)
                        # ensure length
                        if len(row) < len(self.PRED_ROWS_COLUMNS):
                            row = row + [None] * (len(self.PRED_ROWS_COLUMNS) - len(row))
                        else:
                            row = row[:len(self.PRED_ROWS_COLUMNS)]
                    else:
                        # unsupported shape -> skip
                        continue
                    # ensure task_id and mode are set
                    if not row[0]:
                        row[0] = task_id
                    if not row[1]:
                        row[1] = mode
                    to_insert.append(tuple(row))

                    # flush batches
                    if len(to_insert) >= BATCH_INSERT_SIZE:
                        cur.executemany(insert_sql, to_insert)
                        to_insert = []

                if to_insert:
                    cur.executemany(insert_sql, to_insert)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    #
    # Simple fetch of canonical JSON results
    #
    def fetch_results(self, task_id: str) -> Optional[List[Dict[str, Any]]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT results FROM prediction_results WHERE task_id = ?", (task_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None

    def clear_results(self, task_id: str) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM prediction_results WHERE task_id = ?", (task_id,))
        cur.execute("DELETE FROM prediction_rows WHERE task_id = ?", (task_id,))
        conn.commit()
        conn.close()

    #
    # Streaming CSV export for a given task_id.
    #
    def stream_results_csv(self, task_id: str):
        """
        Returns a Flask streaming generator that yields CSV rows for prediction_rows for task_id.
        This is memory-efficient and suitable for the desktop client to download large results.
        """
        def gen():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # prefer time-ordered column if present
            # use Obs_Time if present, else max_time_utc, else rowid
            order_clause = "ORDER BY Obs_Time"  # fine even if column contains NULLs
            try:
                cur.execute(f"SELECT * FROM prediction_rows WHERE task_id = ? {order_clause}", (task_id,))
            except Exception:
                # fallback: select without order
                cur.execute("SELECT * FROM prediction_rows WHERE task_id = ?", (task_id,))

            first = True
            writer = None
            for row in cur:
                # on first row build CSV header
                if first:
                    if row["mode"] == "precise":
                        columns = COLUMN_ORDER_PRECISE_EXPORT
                    else:
                        columns = row.keys()
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow(columns)
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate(0)
                    first = False

                # write the actual row
                buf = io.StringIO()
                writer = csv.writer(buf)
                # Precise CSV/export includes SolarPhaseAngle and intentionally
                # excludes the internal time_of_day/light_phase labels.
                writer.writerow([row[col] for col in columns])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

            conn.close()

        return gen

    #
    # Backwards-compatible exporter for whole tables (small datasets)
    #
    def export_data(self, dataset_name, format="csv"):
        # keep existing behavior for small exports
        if dataset_name == "prediction_rows":
            # return CSV string for small-to-moderate sizes
            conn = sqlite3.connect(self.db_path)
            import pandas as pd
            df = pd.read_sql_query(f"SELECT * FROM {dataset_name}", conn)
            conn.close()
            if format == "csv":
                return df.to_csv(index=False)
            elif format == "json":
                return df.to_json(orient="records")
            return None
        else:
            # fallback to previous results table behavior
            conn = sqlite3.connect(self.db_path)
            import pandas as pd
            df = pd.read_sql_query(f"SELECT * FROM {dataset_name}", conn)
            conn.close()
            if format == "csv":
                return df.to_csv(index=False)
            elif format == "json":
                return df.to_json(orient="records")
            return None
