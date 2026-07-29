from datetime import datetime, timedelta, timezone

def calculate_timezone_offset():
    """Calculate the timezone offset based on the local time."""
    local_time = datetime.now()
    utc_time = local_time.astimezone(timezone.utc).replace(tzinfo=None)
    timezone_offset = (local_time - utc_time).total_seconds() / 3600  # Offset in hours
    return int(timezone_offset)

def get_date_time_object(time_parameters, timezone_offset):
    """
    Compute start and finish datetime objects based on time parameters.

    Parameters:
        time_parameters (dict): Contains "year", "month", "day", "window" keys.
        timezone_offset (int): Timezone offset in hours.

    Returns:
        tuple: Start and finish datetime objects.
    """
    window = time_parameters["window"].lower()
    if window not in ["morning", "evening", "both"]:
        raise ValueError("Window must be: 'morning', 'evening', or 'both'.")

    start_hour = 0 if window == "morning" else 12
    start_date_time = datetime(
        year=time_parameters["year"],
        month=time_parameters["month"],
        day=time_parameters["day"],
        hour=start_hour,
        minute=0,
        second=0,
    ) - timedelta(hours=timezone_offset)

    finish_date_time = start_date_time + timedelta(hours=12 if window in ["morning", "evening"] else 24)
    return start_date_time, finish_date_time
