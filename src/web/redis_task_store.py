# src/web/redis_task_store.py
import os
import json
import gzip
import logging
from pathlib import Path
from typing import Any

from src.prediction_core.precise_materialization import infer_precise_column_order
# Canonical current Overpass schema; see GRR-008 for the tracked follow-up to
# consolidate the duplicate copy in predict_routes.py and the distinct legacy
# predictor_gui.py variant.
from src.prediction_core.parallel_backend import COLUMN_ORDER_OVERPASS

logger = logging.getLogger(__name__)

# Redis client (same as before in your codebase)
import redis
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
TASK_EXPIRATION_SECONDS = int(os.environ.get("TASK_EXPIRATION_SECONDS", str(60 * 60)))

_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# Where to save large raw results
RAW_RESULTS_DIR = Path(os.environ.get("RAW_RESULTS_DIR", "data/raw_results"))
RAW_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Thresholds
SAVE_TO_FILE_MIN_ROWS = int(os.environ.get("SAVE_TO_FILE_MIN_ROWS", "10000"))
SAVE_TO_FILE_MIN_BYTES = int(os.environ.get("SAVE_TO_FILE_MIN_BYTES", str(1_000_000)))  # 1MB

# Known column orders.  Precise supports legacy 18-column rows,
# COLUMN_ORDER_PRECISE_WITH_PHASE-style 20-column rows with internal labels,
# and current 21-column rows with SolarPhaseAngle plus internal labels via
# infer_precise_column_order(...).


def _write_ndjson_gz(path: Path, iterable) -> int:
    """
    Write iterable of JSON-serializable objects to gzipped NDJSON file.
    If a record is a list/tuple, attempt to map it to a dict
    using known column orders (precise/overpass). If neither matches,
    produce col_0..col_n keys so we still persist values.
    Returns number of records written.
    """
    count = 0
    tmp = path.with_suffix(".tmp.ndjson.gz")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as gz:
            for rec in iterable:
                # If rec is a list/tuple, map to dict with best-fit column order
                if isinstance(rec, (list, tuple)):
                    precise_columns = infer_precise_column_order(rec)
                    if precise_columns is not None:
                        rec_obj = dict(zip(precise_columns, rec))
                    elif len(rec) == len(COLUMN_ORDER_OVERPASS):
                        rec_obj = dict(zip(COLUMN_ORDER_OVERPASS, rec))
                    else:
                        # Fallback: create generic col_N keys only for unknown contracts.
                        rec_obj = {f"col_{i}": v for i, v in enumerate(rec)}
                elif hasattr(rec, "to_dict"):
                    # pandas Series etc.
                    try:
                        rec_obj = rec.to_dict()
                    except Exception:
                        rec_obj = dict(rec)
                elif isinstance(rec, dict):
                    rec_obj = rec
                else:
                    # unknown, coerce to string in a wrapper
                    rec_obj = {"raw": str(rec)}

                # json.dumps with safe default for non-serializable types
                gz.write(json.dumps(rec_obj, default=str, separators=(",", ":")))
                gz.write("\n")
                count += 1
        tmp.replace(path)
        return count
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

def register_task(task_id: str, status: str = "running", cancel_flag: bool = False,
                  constraints: dict | None = None, metadata: dict | None = None) -> None:
    key = f"task:{task_id}"
    data = {
        "status": status,
        "cancel_flag": bool(cancel_flag),
        "constraints": constraints or {},
        "metadata": metadata or {}
    }
    try:
        _redis.setex(key, TASK_EXPIRATION_SECONDS, json.dumps(data))
    except Exception:
        logger.exception("register_task failed for %s", task_id)


def update_task_status(task_id: str, status: str) -> None:
    key = f"task:{task_id}"
    try:
        raw = _redis.get(key)
        if raw:
            data = json.loads(raw)
        else:
            data = {}
        data["status"] = status
        if status == "cancelled":
            data["cancel_flag"] = True
        _redis.setex(key, TASK_EXPIRATION_SECONDS, json.dumps(data))
    except Exception:
        logger.exception("update_task_status failed for %s", task_id)


# def _write_ndjson_gz(path: Path, iterable) -> int:
#     """
#     Write iterable of JSON-serializable objects to gzipped NDJSON file.
#     Returns number of records written.
#     """
#     count = 0
#     tmp = path.with_suffix(".tmp.ndjson.gz")
#     try:
#         with gzip.open(tmp, "wt", encoding="utf-8") as gz:
#             for rec in iterable:
#                 gz.write(json.dumps(rec, default=str))
#                 gz.write("\n")
#                 count += 1
#         tmp.replace(path)
#         return count
#     finally:
#         if tmp.exists():
#             try:
#                 tmp.unlink()
#             except Exception:
#                 pass


def store_task_result(task_id: str, results: Any, status: str = "completed") -> None:
    """
    Persist results payload. If results is a very large list, write gzipped NDJSON to disk
    and store a pointer in Redis instead of inlining full JSON in Redis.
    Redis payload shape always remains: {"status": "<status>", "results": [...] } OR
    {"status":"<status>", "pointer":"file://<abs_path>", "count": N}
    """
    payload_key = f"task:{task_id}:payload"
    task_key = f"task:{task_id}"

    try:
        # If results is a dict (for errors), just store it inline
        if isinstance(results, dict) and ("error" in results or "message" in results):
            payload = {"status": status, "results": results}
            _redis.setex(payload_key, TASK_EXPIRATION_SECONDS, json.dumps(payload))
            # sync small record
            raw = _redis.get(task_key)
            small = json.loads(raw) if raw else {}
            small["status"] = status
            _redis.setex(task_key, TASK_EXPIRATION_SECONDS, json.dumps(small))
            return

        # If results is a list-like large payload, decide whether to write file
        if isinstance(results, list):
            n = len(results)
            # estimate bytes by serializing a small sample (cheap heuristic)
            sample_bytes = 0
            try:
                sample = json.dumps(results[:10], default=str)
                sample_bytes = len(sample)
            except Exception:
                sample_bytes = 0

            should_write_file = (n >= SAVE_TO_FILE_MIN_ROWS) or (sample_bytes >= SAVE_TO_FILE_MIN_BYTES)
            if should_write_file:
                fname = RAW_RESULTS_DIR / f"{task_id}.ndjson.gz"
                written = _write_ndjson_gz(fname, results)
                # write file and store pointer + an HTTP download URL for convenience
                payload = {
                    "status": status,
                    "pointer": f"file://{fname.resolve()}",
                    "count": written,
                    # an HTTP endpoint clients can use to download/stream this file:
                    "http_pointer": f"/api/download_results/{task_id}"
                }
                _redis.setex(payload_key, TASK_EXPIRATION_SECONDS, json.dumps(payload))
                logger.info("Wrote large payload for %s -> %s (%d rows)", task_id, fname, written)
                # sync small record
                raw = _redis.get(task_key)
                small = json.loads(raw) if raw else {}
                small["status"] = status
                small.setdefault("metadata", {})["raw_pointer"] = str(fname.resolve())
                # also include http pointer in canonical task record metadata
                small["metadata"]["http_pointer"] = payload["http_pointer"]
                _redis.setex(task_key, TASK_EXPIRATION_SECONDS, json.dumps(small))
                return

        # default: inline store
        payload = {"status": status, "results": results}
        _redis.setex(payload_key, TASK_EXPIRATION_SECONDS, json.dumps(payload))
        raw = _redis.get(task_key)
        small = json.loads(raw) if raw else {}
        small["status"] = status
        _redis.setex(task_key, TASK_EXPIRATION_SECONDS, json.dumps(small))
    except Exception:
        logger.exception("store_task_result failed for %s", task_id)


def get_task_status(task_id: str) -> str | None:
    key = f"task:{task_id}"
    try:
        raw = _redis.get(key)
        if raw:
            data = json.loads(raw)
            if "status" in data:
                return data["status"]
        # fallback to payload
        rawp = _redis.get(f"task:{task_id}:payload")
        if rawp:
            payload = json.loads(rawp)
            return payload.get("status")
    except Exception:
        logger.exception("get_task_status failed for %s", task_id)
    return None


def get_task_result(task_id: str) -> dict | None:
    """
    Return the payload dict. For very large results this will return a pointer payload
    like {"status":"completed","pointer":"file:///abs/path","count":N}
    """
    try:
        raw = _redis.get(f"task:{task_id}:payload")
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("get_task_result failed for %s", task_id)
        return None


def load_results_from_pointer(pointer: str, limit: int | None = None):
    """
    Given a "file://..." pointer, stream-read the NDJSON gz file and yield rows.
    If limit is provided, yield at most `limit` items.
    """
    if not pointer.startswith("file://"):
        raise ValueError("Unsupported pointer scheme")
    path = Path(pointer[len("file://"):])
    if not path.exists():
        raise FileNotFoundError(path)

    count = 0
    with gzip.open(path, "rt", encoding="utf-8") as gz:
        for line in gz:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
            count += 1
            if limit and count >= limit:
                break


def get_task_data(task_id: str):
    key = f"task:{task_id}"
    try:
        raw = _redis.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("get_task_data failed for %s", task_id)
        return None


def cancel_task(task_id: str):
    update_task_status(task_id, "cancelled")
