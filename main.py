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

def connect_wifi():
    global wifi_connection
    if wifi_connection and wifi_connection.isconnected():
        return  # Already connected

    wifi_connection = network.WLAN(network.STA_IF)
    wifi_connection.active(True)

    while not wifi_connection.isconnected():
        print("Attempting to connect to network.")
        wifi_connection.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        time.sleep(5)

    log_to_aws(
        message=f"Connected to network. SSID: {config.WIFI_SSID}. IP Address: {wifi_connection.ifconfig()[0]}",
        level="INFO",
    )


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
        "x-custom-auth": config.AWS_SECRET_TOKEN,
    }
    payload: dict[str, str] = {"message": message, "level": level}

    try:
        # Convert payload to a JSON string
        # MicroPython's requests module does not handle conversions automatically.
        json_payload = json.dumps(payload)
        # Send the POST request with the JSON string
        response = requests.post(config.AWS_LOG_URL, data=json_payload, headers=headers)

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
    Fetches the schedule data from the configured AWS API endpoint and stores it globally.
    Returns True if successful, False otherwise.
    """
    global schedule_data
    
    try:
        headers = {
            "content-type": "application/json",
            "authorization": config.SCHEDULE_API_TOKEN
        }
        
        response = requests.get(config.SCHEDULE_API_URL, headers=headers)
        
        if response.status_code == 200:
            schedule_data = ScheduleData(**response.json())  # Type validation
            response.close()
            
            log_to_aws(
                message="Successfully updated schedule data",
                level="INFO"
            )
            return True
        else:
            response.close()
            log_to_aws(
                message=f"Failed to fetch schedule. Status code: {response.status_code}",
                level="ERROR"
            )
            return False
            
    except Exception as e:
        log_to_aws(
            message=f"Error fetching schedule: {str(e)}",
            level="ERROR"
        )
        return False


def get_duty_for_brightness(v_out: float) -> int:
    # Returns the duty cycle required for a given desired
    #   perceived brightness percentage (0.00 - 1.00 e.g. 0.25 for 25%)
    # Based on https://codeinsecurity.wordpress.com/2023/07/17/the-problem-with-driving-leds-with-pwm/

    return round(config.MAX_DUTY_CYCLE * v_out**2.2)


def generate_brightness_steps(
    warm_start: float,
    warm_stop: float,
    cool_start: float,
    cool_stop: float,
    duration: int,
):
    """Generate brightness values for LED transition.
    
    Args:
        warm_start: Starting warm LED brightness (0.0-1.0)
        warm_stop: Target warm LED brightness (0.0-1.0)
        cool_start: Starting cool LED brightness (0.0-1.0)
        cool_stop: Target cool LED brightness (0.0-1.0)
        duration: Transition duration in seconds
        
    Yields:
        Tuple containing:
        - warm_brightness: Current warm LED brightness (0.0-1.0)
        - cool_brightness: Current cool LED brightness (0.0-1.0)
        - step_delay: Time to wait before next step (seconds)
        
    Raises:
        ValueError: If brightness values outside 0.0-1.0 or duration <= 0
    """
    # Calculate number of steps based on the largest change
    warm_diff = abs(warm_stop - warm_start)
    cool_diff = abs(cool_stop - cool_start)

    # Calculate steps with constraints:
    # 1. Base steps on largest brightness change multiplied by STEPS_MULTIPLIER (default 100)
    #    - This ensures enough steps for smooth transitions (e.g., 0.5 change = 50 steps)
    # 2. Minimum of 1 step to handle no-change scenarios
    # 3. Maximum of MAX_STEPS (default 200) to prevent excessive CPU usage on large changes
    steps = min(max(round(max(warm_diff, cool_diff) * config.STEPS_MULTIPLIER), 1), config.MAX_STEPS)
    
    step_delay = duration / steps
    
    for i in range(steps + 1):  # +1 to include final value
        progress = i / steps
        
        # Linear interpolation for both LEDs
        warm_brightness = warm_start + (warm_stop - warm_start) * progress
        cool_brightness = cool_start + (cool_stop - cool_start) * progress
        
        yield warm_brightness, cool_brightness, step_delay


def get_transition_duration(entry: ScheduleEntry) -> int:
    """
    Calculates the duration until the schedule entry's time in seconds.
    Returns a minimum of 1 minute to prevent instant transitions.
    
    Args:
        entry (ScheduleEntry): The schedule entry containing the target unix_time
    
    Returns:
        int: Number of seconds until the target time, minimum 60 seconds
    """
    now = time.time()
    duration = max(60, entry["unix_time"] - now)  # minimum 1 minute transition
    
    return int(duration)


def run_lighting_transition(entry: ScheduleEntry):
    """
    Runs a lighting transition based on a schedule entry.
    Duration is calculated from the entry's unix_time.
    
    Args:
        entry (ScheduleEntry): The schedule entry containing target brightnesses
    """
    duration = get_transition_duration(entry)
    
    # Get current brightness levels
    current_warm = warm_leds.duty_u16() / config.MAX_DUTY_CYCLE
    current_cool = cool_leds.duty_u16() / config.MAX_DUTY_CYCLE
    
    # Convert target percentages to 0-1 range
    target_warm = entry["warmBrightness"] / 100
    target_cool = entry["coolBrightness"] / 100
    
    log_to_aws(
        message=f"Starting {duration}s transition to {entry['time']} - Warm: {target_warm:.2f}, Cool: {target_cool:.2f}",
        level="DEBUG"
    )
    
    for warm_brightness, cool_brightness, delay in generate_brightness_steps(
        warm_start=current_warm,
        warm_stop=target_warm,
        cool_start=current_cool,
        cool_stop=target_cool,
        duration=duration
    ):
        warm_leds.duty_u16(get_duty_for_brightness(warm_brightness))
        cool_leds.duty_u16(get_duty_for_brightness(cool_brightness))
        time.sleep(delay)
    
    log_to_aws(
        message=f"Completed transition to {entry['time']}",
        level="DEBUG"
    )

def run_schedule_list():
    """
    Runs through the list of schedule entries in time order.
    Only processes entries that are in the future.
    """
    if not schedule_data:
        return
        
    now = time.time()
    
    # Sort entries by unix_time and filter out past events
    future_entries = sorted(
        [entry for entry in schedule_data["schedule"] if entry["unix_time"] > now],
        key=lambda x: x["unix_time"]
    )
    
    for entry in future_entries:
        run_lighting_transition(entry)


def run_named_schedule_entries():
    """
    Runs through the named schedule entries (sunrise, sunset, etc.) in time order.
    Only processes entries that are in the future.
    """
    if not schedule_data:
        return
        
    now = time.time()
    
    # Create list of named entries with their keys
    named_entries = [
        (key, schedule_data[key]) 
        for key in [
            "sunrise", "sunset",
            "civil_twilight_begin", "civil_twilight_end",
            "bed_time", "night_time"
        ]
    ]
    
    # Sort by unix_time and filter out past events
    future_entries = sorted(
        [(key, entry) for key, entry in named_entries if entry["unix_time"] > now],
        key=lambda x: x[1]["unix_time"]
    )
    
    for key, entry in future_entries:
        log_to_aws(
            message=f"Processing named schedule entry: {key}",
            level="INFO"
        )
        run_lighting_transition(entry)


def has_future_events() -> bool:
    """
    Checks if there are any future events in the current schedule mode.
    
    Returns:
        bool: True if future events exist, False otherwise
    """
    if not schedule_data:
        return False
        
    now = time.time()
    
    if schedule_data and schedule_data["mode"] == "scheduled":
        return any(
            entry["unix_time"] > now 
            for entry in schedule_data["schedule"]
        )
    elif schedule_data["mode"] == "dayNight":
        return any(
            schedule_data[key]["unix_time"] > now
            for key in [
                "sunrise", "sunset",
                "civil_twilight_begin", "civil_twilight_end",
                "bed_time", "night_time"
            ]
        )
    else:
        return False


def night_light():
    # Dim warm light
    log_to_aws(
        message="Starting night light mode",
        level="DEBUG",
    )

    warm_leds.duty_u16(get_duty_for_brightness(config.NIGHT_LIGHT_BRIGHTNESS))
    cool_leds.duty_u16(0)


def run_scheduled_tasks():
    """
        Main task scheduler that updates the schedule if needed 
        and runs the specified light mode.
    """
    # Check if we need to fetch a new schedule
    if not schedule_data:
        if not fetch_schedule():
            log_to_aws(
                message="Schedule fetch failed from run_scheduled_task.",
                level="WARNING"
            )
            night_light()  # Fallback to safe mode if fetch fails
            return
    
    elif not has_future_events():
        # If no future events, wait until the next update time
        if time.time() < schedule_data["update_time_unix"]:
            time.sleep(schedule_data["update_time_unix"] - time.time())
            return
    
    elif schedule_data["mode"] == "scheduled":
         # Run the appropriate lighting mode based on schedule data
        run_schedule_list()
    
    elif schedule_data["mode"] == "dayNight":
        run_named_schedule_entries()
    
    elif schedule_data["mode"] == "demo":
        log_to_aws(
            message="Demo mode not implemented",
            level="WARNING"
        ) 
    else:
        log_to_aws(
            message=f"Unknown schedule mode: {schedule_data['mode']}",
            level="ERROR"
        )


try:
    # start at dim setting
    night_light()  

    # Network setup
    connect_wifi()

    # sets the RTC with the unix epoch from the internet
    ntptime.settime()

     # Initial lighting schedule fetch
    fetch_schedule() 

    # Schedule the timer to check every 60,0000 milliseconds (10 minutes)
    #   and run appropriate day/night routine
    timer = machine.Timer()
    timer.init(
        period=600000,
        mode=machine.Timer.PERIODIC,
        callback=lambda t: run_scheduled_tasks(),
    )

    # start lighting cycle
    run_scheduled_tasks()

except KeyboardInterrupt:
    # we can hope this gets logged correctly
    log_to_aws(
        message="System resetting due to Keyboard Interrupt",
        level="INFO",
    )

    machine.reset()
except Exception as e:
    # we can hope this gets logged correctly
    log_to_aws(
        message=f"Unknown error in main: {e}",
        level="ERROR"
    )
