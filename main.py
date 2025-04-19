import network
import requests
import machine
import ntptime
import time
import config
import json
from models import ScheduleData, ScheduleEntry

# Setup Outputs and PWMs globally
warm_leds = machine.PWM(machine.Pin(config.WARM_LED_PIN))
warm_leds.freq(config.PWM_FREQUENCY)

cool_leds = machine.PWM(machine.Pin(config.COOL_LED_PIN))
cool_leds.freq(config.PWM_FREQUENCY)

# Global variable to hold Wi-Fi connection
wifi_connection = None

# Global variable to store the schedule data
schedule_data: ScheduleData | None = None


def connect_wifi(timeout: int = 30) -> bool:
    """
    Attempt a Wi‑Fi connection for *timeout* seconds.
    Returns True on success, False on failure (caller may fall back
    to night‑light mode and retry later).
    """
    global wifi_connection

    if wifi_connection and wifi_connection.isconnected():
        return True

    wifi_connection = network.WLAN(network.STA_IF)
    wifi_connection.active(True)

    start = time.time()
    while not wifi_connection.isconnected() and (time.time() - start) < timeout:
        print("Attempting to connect to network…")
        wifi_connection.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        time.sleep(5)

    if wifi_connection.isconnected():
        log_to_aws(f"Connected.  IP: {wifi_connection.ifconfig()[0]}", "INFO")
        return True

    log_to_aws("Wi‑Fi connect timed out; will retry later.", "ERROR")
    return False


def log_to_aws(message: str, level: str = "INFO") -> None:
    """
    Sends a log message with a specified level to an AWS Lambda URL endpoint.

    Args:
        message (str): The log message to send.
        level (str): The log level (e.g., INFO, ERROR, DEBUG). Default is INFO.
    """
    # Print to console for legibility
    print(f"{level} | {message}")

    # Prepare the headers and payload
    # Lowercase is important for HTTP 2 protocol
    headers: dict[str, str] = {
        "content-type": "application/json",
        "x-custom-auth": config.AWS_LOGGING_SECRET_TOKEN,
    }
    payload: dict[str, str] = {
        "message": message,
        "level": level,
        "service_name": "sunrise-lamp-aws",
        "client_name": config.CLIENT_NAME,
    }

    try:
        # Convert payload to a JSON string
        # MicroPython's requests module does not handle conversions automatically.
        json_payload = json.dumps(payload)
        # Send the POST request with the JSON string
        response = requests.post(
            config.AWS_LOGGING_API, data=json_payload, headers=headers
        )

        # Check the response status
        if response.status_code == 200:
            response.close()
            return
        else:
            print("Failed to send log. Status code:", response.status_code)
            response.close()
            return
    except Exception as e:
        print("Error sending log:", str(e))
        return


def fetch_schedule():
    """
    Fetches lighting schedule data from configured API endpoint.

    Updates global schedule_data with new schedule if successful.
    Schedule data includes times, brightness levels, and mode settings
    for controlling the lighting throughout the day.

    Returns:
        bool: True if schedule was successfully fetched and parsed,
              False if any error occurred
    """
    global schedule_data

    try:
        headers = {
            "content-type": "application/json",
            "x-custom-auth": config.AWS_LIGHTS_SECRET_TOKEN,
        }

        response = requests.get(config.AWS_LIGHT_SCHEDULE_API, headers=headers)

        if response.status_code == 200:
            schedule_data = ScheduleData(**response.json())  # Type validation
            response.close()

            log_to_aws(message="Successfully updated schedule data", level="INFO")
            return True
        else:
            response.close()
            log_to_aws(
                message=f"Failed to fetch schedule. Status code: {response.status_code}",
                level="ERROR",
            )
            return False

    except Exception as e:
        log_to_aws(message=f"Error fetching schedule: {str(e)}", level="ERROR")
        return False


###############################################################################
# Brightness / PWM helpers
###############################################################################
# Uses gamma correction (power of 2.2) to adjust for human perception of LED brightness.
# Based on https://codeinsecurity.wordpress.com/2023/07/17/the-problem-with-driving-leds-with-pwm/
GAMMA: float = 2.2


def brightness_to_duty(brightness: float) -> int:
    """
    Convert a perceptual brightness value (0.0 – 1.0) into a 16‑bit PWM duty.

    Args:
        brightness (float): Desired brightness where 0 = off and 1 = max.

    Returns:
        int: 16‑bit duty value suitable for `PWM.duty_u16()`.
    """
    return round(config.MAX_DUTY_CYCLE * brightness**GAMMA)


def duty_to_brightness(duty: int) -> float:
    """
    Convert a 16‑bit PWM duty value back to perceptual brightness.

    Args:
        duty (int): Raw value returned by `PWM.duty_u16()`.

    Returns:
        float: Brightness in the 0.0 – 1.0 range.
    """
    return (duty / config.MAX_DUTY_CYCLE) ** (1 / GAMMA)


def set_leds(warm: float, cool: float) -> None:
    """
    Write both PWM channels in one call.  *warm* and *cool* are 0‑1 floats.
    """
    warm_leds.duty_u16(brightness_to_duty(warm))
    cool_leds.duty_u16(brightness_to_duty(cool))


def generate_brightness_steps(
    warm_start: float,
    warm_stop: float,
    cool_start: float,
    cool_stop: float,
    duration: int,
):
    """
    Generate brightness transitions at a fixed per‑second rate.

    Args:
        warm_start: Starting warm brightness (0.0–1.0)
        warm_stop: Target warm brightness (0.0–1.0)
        cool_start: Starting cool brightness (0.0–1.0)
        cool_stop: Target cool brightness (0.0–1.0)
        duration: Total transition time, in seconds

    Yields:
        (warm_brightness, cool_brightness, step_delay)
    """
    MAX_STEPS = 2_000  # safety ceiling
    # Number of update steps = duration × updates/sec (at least 1)
    steps_per_second = config.STEPS_PER_SECOND  # e.g. 10
    steps = min(MAX_STEPS, max(1, int(duration * steps_per_second)))
    step_delay = duration / steps

    for i in range(steps + 1):
        progress = i / steps
        warm_brightness = warm_start + (warm_stop - warm_start) * progress
        cool_brightness = cool_start + (cool_stop - cool_start) * progress
        yield warm_brightness, cool_brightness, step_delay


def get_transition_duration(entry: ScheduleEntry) -> int:
    """
    Seconds until the **future** event.  If the entry is already overdue,
    return 60 s so we still fade rather than jump.  Otherwise, use the
    true interval even when it's <60 s (startup at T‑5 s, for example).
    """
    delta = entry["unix_time"] - time.time()
    return 60 if delta <= 0 else max(1, int(delta))


def run_lighting_transition(
    entry: ScheduleEntry,
    *,
    forced_duration: int | None = None,
) -> None:
    """
    Transition the LEDs from their *current* level to the target contained
    in ``entry``.  Duration is normally computed from the entry's unix_time
    but can be overridden (``forced_duration``) when we just want a quick
    sync after boot.

    Args:
        entry (ScheduleEntry):  Target warm / cool brightness levels.
        forced_duration (int | None):  Optional fixed duration in seconds.
    """
    # Either use the forced value or compute time‑to‑target
    duration = forced_duration or get_transition_duration(entry)

    # Read the true perceptual start level using the inverse gamma curve
    current_warm = duty_to_brightness(warm_leds.duty_u16())
    current_cool = duty_to_brightness(warm_leds.duty_u16())

    # Convert schedule percentages into 0‑1 floats
    target_warm = entry["warmBrightness"] / 100
    target_cool = entry["coolBrightness"] / 100

    log_to_aws(
        message=(
            f"Starting {duration}s transition to {entry['time']} — "
            f"Warm: {target_warm:.2f}, Cool: {target_cool:.2f}"
        ),
        level="DEBUG",
    )

    for warm_brightness, cool_brightness, delay in generate_brightness_steps(
        warm_start=current_warm,
        warm_stop=target_warm,
        cool_start=current_cool,
        cool_stop=target_cool,
        duration=duration,
    ):
        set_leds(warm_brightness, cool_brightness)
        time.sleep(delay)

    log_to_aws(message=f"Completed transition to {entry['time']}", level="DEBUG")


def run_schedule_list():
    """
    Executes schedule entries in chronological order.

    Filters out past events, sorts remaining by time,
    Sets current brightness to most recent past event before running future events.
    Only used in 'scheduled' mode.

    Note: Requires valid schedule_data global
    """
    if not schedule_data:
        return

    now = time.time()

    # Sort all entries by unix_time
    sorted_entries: list[ScheduleEntry] = sorted(
        schedule_data["schedule"], key=lambda x: x["unix_time"]
    )

    # Find most recent past event
    past_entries = [entry for entry in sorted_entries if entry["unix_time"] <= now]

    if past_entries:
        # Set current brightness to most recent past event
        set_leds(
            past_entries[-1]["warmBrightness"] / 100,
            past_entries[-1]["coolBrightness"] / 100,
        )

    # Process future events
    future_entries: list[ScheduleEntry] = [
        entry for entry in sorted_entries if entry["unix_time"] > now
    ]

    for entry in future_entries:
        # Run transition for each future event
        run_lighting_transition(entry)


def run_named_schedule_entries():
    """
    Executes named schedule entries in chronological order.
    Sets current brightness to most recent past event before running future events.
    Only used in 'dayNight' mode.

    Note: Requires valid schedule_data global
    """
    if not schedule_data:
        return

    now = time.time()

    # Create list of named entries with their keys
    named_entries: list[tuple[str, ScheduleEntry]] = [
        (key, schedule_data[key])
        for key in config.NAMED_SCHEDULE_KEYS
        if key in schedule_data
    ]

    # Sort chronologically
    named_entries.sort(key=lambda kv: kv[1]["unix_time"])

    # Sync LEDs to the last past event with a fast, eye‑safe fade
    past = [(k, e) for k, e in named_entries if e["unix_time"] <= now]
    if past:
        _, last_entry = past[-1]
        run_lighting_transition(last_entry, forced_duration=2)

    # Transition through every future event
    for key, entry in named_entries:
        if entry["unix_time"] > now:
            log_to_aws(message=f"Processing named schedule entry: {key}", level="INFO")
            run_lighting_transition(entry)


def has_future_events() -> bool:
    """
    Checks if current schedule has any future events.

    For 'scheduled' mode: checks schedule list
    For 'dayNight' mode: checks named schedule entries
    Compares event unix_time against current time

    Returns:
        bool: True if any future events exist in current mode,
              False if no future events or no schedule
    """
    if not schedule_data:
        return False

    now = time.time()

    if schedule_data and schedule_data["mode"] == "scheduled":
        return any(entry["unix_time"] > now for entry in schedule_data["schedule"])
    elif schedule_data["mode"] == "dayNight":
        return any(
            schedule_data[key]["unix_time"] > now for key in config.NAMED_SCHEDULE_KEYS
        )
    else:
        return False


def night_light():
    # Dim warm light
    log_to_aws(
        message="Starting night light mode",
        level="DEBUG",
    )

    set_leds(config.NIGHT_LIGHT_BRIGHTNESS, 0)


def run_demo_cycle():
    """
    Runs a compressed day/night demonstration cycle.

    Simulates a full day in 10 seconds:
    1. Night → Dawn (2s): Warm up from night light
    2. Dawn → Morning (2s): Introduce cool light
    3. Daylight hold (2s): Full brightness
    4. Evening (2s): Reduce cool light
    5. Dusk → Night (2s): Dim to night light

    Used for testing and demonstration purposes
    """
    log_to_aws(message="Starting demo light cycle", level="INFO")

    # Night to Dawn (dark warm to bright warm)
    for warm_brightness, cool_brightness, delay in generate_brightness_steps(
        warm_start=0.25,  # night light level
        warm_stop=1.0,  # full warm
        cool_start=0.0,
        cool_stop=0.0,
        duration=2,  # 2 seconds
    ):
        set_leds(warm_brightness, cool_brightness)
        time.sleep(delay)

    # Dawn to Morning (introduce cool light)
    for warm_brightness, cool_brightness, delay in generate_brightness_steps(
        warm_start=1.0, warm_stop=0.75, cool_start=0.0, cool_stop=1.0, duration=2
    ):
        set_leds(warm_brightness, cool_brightness)
        time.sleep(delay)

    # Hold daylight for 2 seconds
    time.sleep(2)

    # Evening (reduce cool light)
    for warm_brightness, cool_brightness, delay in generate_brightness_steps(
        warm_start=0.75, warm_stop=1.0, cool_start=1.0, cool_stop=0.0, duration=2
    ):
        set_leds(warm_brightness, cool_brightness)
        time.sleep(delay)

    # Dusk to Night (dim warm light to night level)
    for warm_brightness, cool_brightness, delay in generate_brightness_steps(
        warm_start=1.0, warm_stop=0.25, cool_start=0.0, cool_stop=0.0, duration=2
    ):
        set_leds(warm_brightness, cool_brightness)
        time.sleep(delay)

    log_to_aws(message="Completed demo light cycle", level="INFO")


def run_scheduled_tasks():
    """
    Main scheduling function that manages lighting updates.

    Checks schedule validity and mode:
    - Fetches new schedule if needed
    - Runs appropriate mode handler (scheduled/dayNight/demo)
    - Handles schedule transitions and updates
    - Falls back to night light mode on errors

    Called periodically by timer to maintain lighting schedule
    """
    # Attempt to update the RTC to correct any drift
    try:
        ntptime.settime()
    except Exception as e:
        log_to_aws(message=f"Failed to update time: {e}", level="ERROR")

    if schedule_data and schedule_data["mode"] == "demo":
        # Demo mode runs its own cycle forever
        while True:
            run_demo_cycle()

    # Check if we need to fetch a new schedule
    if schedule_data is None or not has_future_events():
        # If no future events, wait until the next update time
        if schedule_data and time.time() < schedule_data["update_time_unix"]:
            time.sleep(schedule_data["update_time_unix"] - time.time())

        # get new schedule
        fetch_schedule()

    elif schedule_data["mode"] == "scheduled":
        # Run the appropriate lighting mode based on schedule data
        run_schedule_list()

    elif schedule_data["mode"] == "dayNight":
        run_named_schedule_entries()

    else:
        log_to_aws(
            message=f"Unknown schedule mode: {schedule_data['mode']}", level="ERROR"
        )


try:
    night_light()  # safe startup level
    connect_wifi()  # non‑blocking try
    ntptime.settime()  # sync RTC (best‑effort)
    fetch_schedule()  # first schedule pull

    NEXT_RUN = time.time()  # scheduler heartbeat

    while True:
        if time.time() >= NEXT_RUN:
            run_scheduled_tasks()
            NEXT_RUN += 600  # every 10 min
        time.sleep(1)  # idle‑sleep to save CPU

except KeyboardInterrupt:
    # we can hope this gets logged correctly
    log_to_aws(
        message="System resetting due to Keyboard Interrupt",
        level="INFO",
    )

    machine.reset()
except Exception as e:
    # we can hope this gets logged correctly
    log_to_aws(message=f"Unknown error in main: {e}", level="ERROR")
