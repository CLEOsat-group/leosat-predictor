import sqlite3
import os

def initialize_database(db_path: str = "data/satellite_data.db") -> None:
    """Ensure the DB file and required tables/indexes exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Run as a single script so it's atomic and idempotent
    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS prediction_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT UNIQUE,
        mode TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        observer_lat REAL,
        observer_lon REAL,
        observer_alt REAL,
        observer_name TEXT,
        results JSON
    );

    CREATE TABLE IF NOT EXISTS prediction_rows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        mode TEXT,
        Sat_ID TEXT,
        Obs_Time TEXT,
        Local_Time TEXT,
        UT_Date TEXT,
        UT_time TEXT,
        SatRA TEXT,
        SatDEC TEXT,
        SatAz REAL,
        SatElev REAL,
        SolarPhaseAngle REAL,
        SatAlt REAL,
        SatDist REAL,
        SunRA REAL,
        SunDEC REAL,
        SunZenithAngle REAL,
        RA REAL,
        DEC REAL,
        SatLon REAL,
        SatLat REAL,
        -- Overpass-specific fields (nullable for precise rows)
        rise_time_loc TEXT,
        max_time_loc TEXT,
        set_time_loc TEXT,
        rise_time_utc TEXT,
        max_time_utc TEXT,
        set_time_utc TEXT,
        rise_azimuth REAL,
        max_elevation REAL,
        set_azimuth REAL,
        SatAzRise REAL,
        SatElevRise REAL,
        SatAltRise REAL,
        SatDistRise REAL,
        SatLonRise REAL,
        SatLatRise REAL,
        SatAzSet REAL,
        SatElevSet REAL,
        SatAltSet REAL,
        SatDistSet REAL,
        SatLonSet REAL,
        SatLatSet REAL,
        -- Lightweight derived columns for fast filtering/plotting
        time_of_day TEXT,
        light_phase TEXT,
        -- link back to canonical results (optional)
        FOREIGN KEY(task_id) REFERENCES prediction_results(task_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_prediction_rows_task_id ON prediction_rows(task_id);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_task_sat ON prediction_rows(task_id, Sat_ID);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_sat_id ON prediction_rows(Sat_ID);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_obs_time ON prediction_rows(Obs_Time);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_max_time_utc ON prediction_rows(max_time_utc);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_sat_elev ON prediction_rows(SatElev);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_mode ON prediction_rows(mode);
    CREATE INDEX IF NOT EXISTS idx_prediction_rows_time_of_day ON prediction_rows(time_of_day);
    """)

    # Lightweight migration for existing development databases created before
    # Task 25E. SQLite keeps this idempotent by checking PRAGMA metadata first.
    cur.execute("PRAGMA table_info(prediction_rows)")
    existing_columns = {row[1] for row in cur.fetchall()}
    if "SolarPhaseAngle" not in existing_columns:
        cur.execute("ALTER TABLE prediction_rows ADD COLUMN SolarPhaseAngle REAL")

    conn.commit()
    conn.close()

# import sqlite3
# import os
#
#
# def initialize_database(db_path="data/satellite_data.db"):
#     """Initialize the database with the required tables."""
#
#     # Ensure the data directory exists
#     os.makedirs(os.path.dirname(db_path), exist_ok=True)
#
#     conn = sqlite3.connect(db_path)
#     cursor = conn.cursor()
#
#     # Table to store prediction results
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS prediction_results (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             task_id TEXT UNIQUE,
#             mode TEXT,
#             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
#             observer_lat REAL,
#             observer_lon REAL,
#             observer_alt REAL,
#             observer_name TEXT,
#             results JSON
#         )
#     """)
#
#     # # Create indexes on task_id and mode columns
#     # cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_id ON prediction_results(task_id)")
#     # cursor.execute("CREATE INDEX IF NOT EXISTS idx_mode ON prediction_results(mode)")
#
#     conn.commit()
#     conn.close()
