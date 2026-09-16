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

    # Windows follow the human observing-night convention for the selected date:
    #   evening -> noon of the selected day to midnight (12 h)
    #   morning -> midnight to noon of the FOLLOWING day (12 h)
    #   both    -> noon of the selected day to noon of the following day (24 h)
    # "morning" therefore starts one day after the selected date so that it
    # refers to the same early hours as the morning half of "both"; anchoring
    # it to the selected day's midnight pointed a full day too early and could
    # never overlap the "both" window.
    selected_midnight = datetime(
        year=time_parameters["year"],
        month=time_parameters["month"],
        day=time_parameters["day"],
        hour=0,
        minute=0,
        second=0,
    )
    if window == "morning":
        start_local = selected_midnight + timedelta(days=1)
        duration_hours = 12
    elif window == "evening":
        start_local = selected_midnight + timedelta(hours=12)
        duration_hours = 12
    else:  # both
        start_local = selected_midnight + timedelta(hours=12)
        duration_hours = 24

    start_date_time = start_local - timedelta(hours=timezone_offset)
    finish_date_time = start_date_time + timedelta(hours=duration_hours)
    return start_date_time, finish_date_time
