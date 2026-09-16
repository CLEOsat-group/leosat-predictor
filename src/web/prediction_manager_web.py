# src/web/prediction_manager_web.py
import threading
import uuid
import json
import logging
from typing import Dict, Any, Optional, Iterable

from src.web.prediction_thread_web import PredictionThreadWeb
from src.web import redis_task_store as rts

logger = logging.getLogger(__name__)


class PredictionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, PredictionThreadWeb] = {}

    def start_task(self, mode, satellites, location,
                   start_datetime, end_datetime, days, interval,
                   margin, constraints) -> str:
        task_id = str(uuid.uuid4())
        logger.info("Starting prediction task %s", task_id)

        rts.register_task(task_id, status="running", cancel_flag=False, constraints=constraints, metadata={"mode": mode})

        pt = PredictionThreadWeb(
            task_id=task_id,
            mode=mode,
            satellites=satellites,
            location=location,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            days=days,
            interval=interval,
            margin=margin,
            constraints=constraints,
        )

        with self._lock:
            self._tasks[task_id] = pt

        pt.start()
        watcher = threading.Thread(target=self._watch_and_persist, args=(task_id, pt), daemon=True)
        watcher.start()

        return task_id

    def _watch_and_persist(self, task_id: str, pt: PredictionThreadWeb):
        try:
            pt.join(timeout=None)

            # cancelled
            status = rts.get_task_status(task_id)
            if status == "cancelled" or pt.is_cancelled():
                rts.update_task_status(task_id, "cancelled")
                rts.store_task_result(task_id, [], status="cancelled")
                logger.info("Task %s cancelled", task_id)
                return

            if pt.error:
                logger.error("Task %s failed: %s", task_id, pt.error)
                rts.update_task_status(task_id, "error")
                rts.store_task_result(task_id, {"error": str(pt.error)}, status="error")
                return

            results = pt.results or []
            rts.update_task_status(task_id, "completed")
            rts.store_task_result(task_id, results, status="completed")

            # OPTIONAL: compute and store a small aggregate summary in canonical small record
            try:
                # compute a cheap aggregate: total samples and per-sat sample counts (top-level)
                total = len(results) if isinstance(results, list) else 0
                small = rts.get_task_data(task_id) or {}
                meta = small.get("metadata", {})
                meta["total_samples"] = total
                # you can add more aggregates here (e.g., per-sat counts), but be mindful of cost
                small["metadata"] = meta
                rts._redis.setex(f"task:{task_id}", rts.TASK_EXPIRATION_SECONDS, json.dumps(small))
            except Exception:
                logger.exception("Failed to write small aggregate for %s", task_id)

            logger.info("Task %s completed and persisted (%d rows)", task_id, len(results))
        except Exception as exc:
            logger.exception("Watcher for task %s failed: %s", task_id, exc)
            try:
                rts.update_task_status(task_id, "error")
                rts.store_task_result(task_id, {"error": str(exc)}, status="error")
            except Exception:
                logger.exception("Failed to persist error for %s", task_id)
        finally:
            with self._lock:
                self._tasks.pop(task_id, None)

    def get_status(self, task_id: str) -> str:
        status = rts.get_task_status(task_id)
        if status:
            return status
        with self._lock:
            pt = self._tasks.get(task_id)
        if pt is None:
            return "unknown"
        if pt.is_alive():
            return "running"
        return "completed" if not pt.error else "error"

    def get_results(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Return persisted payload dict if present (may be pointer payload).
        If not present and the worker finished, synthesize the payload from in-memory worker.
        """
        payload = rts.get_task_result(task_id)
        if payload is not None:
            return payload

        with self._lock:
            pt = self._tasks.get(task_id)
        if pt is None:
            return None
        if pt.is_alive():
            return {"status": "running", "results": []}
        if pt.error:
            return {"status": "error", "results": {"error": str(pt.error)}}
        return {"status": "completed", "results": pt.results or []}

    def load_pointer_materialized(self, pointer_payload: dict, limit: int | None = None) -> list:
        """
        pointer_payload is something returned by rts.get_task_result, e.g.
        {"status":"completed","pointer":"file:///abs/path","count":N}
        This will stream and materialize up to `limit` rows (or all if None).
        """
        pointer = pointer_payload.get("pointer")
        if not pointer:
            raise ValueError("No pointer in payload")
        # use redis_task_store helper to stream
        return list(rts.load_results_from_pointer(pointer, limit=limit))

    def load_pointer_aggregate(self, pointer_payload: dict) -> dict:
        """
        Stream the pointer file once and compute a lightweight aggregate.
        Returns dict with summary (total count, per-sat sample counts, t_min/t_max).
        This is suitable for quick plotting.
        """
        pointer = pointer_payload.get("pointer")
        if not pointer:
            raise ValueError("No pointer in payload")

        # naive, memory-light streaming aggregate
        it = rts.load_results_from_pointer(pointer)
        total = 0
        per_sat = {}
        t_min = {}
        t_max = {}
        from dateutil.parser import parse as parse_date
        for rec in it:
            total += 1
            # rec could be list or dict depending on your worker output shape
            # Try robust extraction: prefer Sat_ID and Obs_Time or max_time_utc
            sat_id = None
            ts = None
            if isinstance(rec, dict):
                sat_id = rec.get("Sat_ID")
                ts = rec.get("Obs_Time") or rec.get("max_time_utc")
            elif isinstance(rec, list):
                # fallback mapping (user must ensure consistent column ordering)
                # We cannot safely guess column indices universally; best-effort:
                try:
                    sat_id = rec[0]
                    # times often in index 1 or 4 depending on precise/overpass; try both
                    ts = rec[1] if len(rec) > 1 else None
                except Exception:
                    sat_id = None
                    ts = None

            if sat_id is None:
                sat_id = "UNKNOWN"

            per_sat.setdefault(sat_id, 0)
            per_sat[sat_id] += 1

            # parse ts if possible
            if ts:
                try:
                    p = parse_date(str(ts))
                    if sat_id not in t_min or p < t_min[sat_id]:
                        t_min[sat_id] = p
                    if sat_id not in t_max or p > t_max[sat_id]:
                        t_max[sat_id] = p
                except Exception:
                    pass

        # convert datetime to strings
        per_sat_summary = []
        for sat, cnt in per_sat.items():
            tmin_s = t_min.get(sat).strftime("%Y-%m-%dT%H:%M:%S") if t_min.get(sat) else None
            tmax_s = t_max.get(sat).strftime("%Y-%m-%dT%H:%M:%S") if t_max.get(sat) else None
            per_sat_summary.append({"Sat_ID": sat, "samples": cnt, "t_min": tmin_s, "t_max": tmax_s})

        return {"total": total, "per_sat": per_sat_summary}

    def get_constraints(self, task_id: str):
        data = rts.get_task_data(task_id) or {}
        return data.get("constraints") or {}

    def cancel_task(self, task_id: str):
        rts.cancel_task(task_id)
        with self._lock:
            pt = self._tasks.get(task_id)
        if pt:
            logger.info("Requested cancel for %s", task_id)


prediction_manager = PredictionManager()
