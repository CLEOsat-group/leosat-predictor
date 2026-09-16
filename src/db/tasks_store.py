"""
src/db/tasks_store.py

Helpers:
 - initialize_database(db_path)
 - compute_payload_hash(obj) -> str
 - get_or_create_task(db_path, payload_obj, mode, initial_status='queued', metadata=None) -> (task_id, created)
 - update_task_status(db_path, task_id, status, started_at=None, finished_at=None, metadata=None, result_pointer=None, results_json=None)
"""

import sqlite3
import json
import hashlib
import time
from datetime import datetime
from typing import Tuple, Optional, Any


def iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def compute_payload_hash(payload_obj: Any) -> str:
    """
    Deterministic canonical JSON -> SHA256 hex digest.
    Use sort_keys=True and compact separators for stable hashing.
    """
    j = json.dumps(payload_obj or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    h = hashlib.sha256(j.encode("utf-8")).hexdigest()
    return h


def initialize_database(db_path: str):
    """
    Run the migration SQL (idempotent) to create tables & pragmas.
    """
    migration_sql = """
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA foreign_keys = ON;
    PRAGMA busy_timeout = 5000;

    CREATE TABLE IF NOT EXISTS tasks (
        task_id       TEXT PRIMARY KEY,
        payload_hash  TEXT NOT NULL,
        status        TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        started_at    TEXT,
        finished_at   TEXT,
        mode          TEXT,
        metadata      JSON,
        result_pointer TEXT,
        results_json  JSON
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_payload_hash ON tasks(payload_hash);

    CREATE TABLE IF NOT EXISTS prediction_results (
        task_id       TEXT PRIMARY KEY,
        mode          TEXT,
        observer_lat  REAL,
        observer_lon  REAL,
        observer_alt  REAL,
        observer_name TEXT,
        results_json  JSON,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    );
    """
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        # Apply PRAGMA and migration
        conn.executescript(migration_sql)
        conn.commit()
    finally:
        conn.close()


def get_or_create_task(db_path: str, payload_obj: dict, mode: str,
                       initial_status: str = "queued",
                       metadata: Optional[dict] = None) -> Tuple[str, bool]:
    """
    Single-flight helper: try to INSERT a new task row with INSERT OR IGNORE keyed by payload_hash.
    Returns (task_id, created_flag) where created_flag==True if we inserted a new task,
    otherwise returns the existing task_id (created_flag==False).

    Important: you must set `task_id` externally if you want UUID format or let this function
    generate one (it uses timestamp+hash suffix to be short but unique).
    """
    payload_hash = compute_payload_hash(payload_obj)
    created = False

    conn = sqlite3.connect(db_path, timeout=5)
    # ensure we get rows as tuples, but we just use simple selects
    try:
        # Make PRAGMAs explicit for this connection
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout = 5000")

        cur = conn.cursor()
        # Use a transaction block to reduce race window
        # INSERT OR IGNORE will not fail if another concurrent insert created the row.
        # After the INSERT OR IGNORE we SELECT the row (either newly created or existing).
        now = iso_now()

        # Generate a lightweight unique task id if you don't want to supply one:
        # (use uuid4 in your application if preferred)
        import uuid
        new_task_id = str(uuid.uuid4())

        # Insert or ignore
        cur.execute(
            "BEGIN IMMEDIATE"
        )
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO tasks (task_id, payload_hash, status, created_at, mode, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_task_id, payload_hash, initial_status, now, mode, json.dumps(metadata or {}))
            )
        except Exception:
            # still safe to continue to select state
            pass

        # Now select the canonical row for this payload_hash
        cur.execute(
            "SELECT task_id, status FROM tasks WHERE payload_hash = ?",
            (payload_hash,)
        )
        row = cur.fetchone()
        if row:
            task_id = row[0]
            status = row[1]
        else:
            # Very unlikely: fallback to the generated id
            task_id = new_task_id
            status = initial_status

        conn.commit()
    finally:
        conn.close()

    # created_flag -> True if we inserted (i.e., task_id == new_task_id)
    created = (task_id == new_task_id)
    return task_id, created


def update_task_status(db_path: str, task_id: str, status: str,
                       started_at: Optional[str] = None,
                       finished_at: Optional[str] = None,
                       metadata: Optional[dict] = None,
                       result_pointer: Optional[str] = None,
                       results_json: Optional[Any] = None) -> None:
    """
    Update status and optional columns. This helper writes only provided fields.
    """
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        # build dynamic SET clause
        sets = ["status = ?"]
        params = [status]

        if started_at is not None:
            sets.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            sets.append("finished_at = ?")
            params.append(finished_at)
        if metadata is not None:
            sets.append("metadata = ?")
            params.append(json.dumps(metadata))
        if result_pointer is not None:
            sets.append("result_pointer = ?")
            params.append(result_pointer)
        if results_json is not None:
            # results_json can be a list/dict; dump to string
            sets.append("results_json = ?")
            params.append(json.dumps(results_json))

        params.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?"
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def fetch_task_row(db_path: str, task_id: str) -> Optional[dict]:
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA busy_timeout = 5000")
        cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


# Example usage
if __name__ == "__main__":
    DB = "data/tasks.db"
    initialize_database(DB)

    payload = {"mode": "precise", "satellites": ["SAT-1", "SAT-2"], "lat": 12.34, "lon": -56.78}
    tid, created = get_or_create_task(DB, payload, mode="precise")
    print("task_id:", tid, "created:", created)
    # If created==True -> caller should start the worker for tid
    # If created==False -> there's already a task with same payload; fetch status/metadata or reuse.
