# =============================================================================
# Device Identification
# =============================================================================
CLIENT_NAME = "Sunrise Lamp"  # Name of the device for logging

# Service name for logging to AWS CloudWatch
LOGGING_SERVICE_NAME = "sunrise-lamp-aws"

# =============================================================================
# WiFi Credentials
# =============================================================================
WIFI_SSID = "wifi_name"          # Network name to connect to
WIFI_PASSWORD = "wifi_password"  # Network password

# =============================================================================
# PWM Settings
# =============================================================================
# IEEE 1789-2015 recommends PWM frequency > 3000Hz to prevent visible flicker
# We double this for safety margin and smooth operation
PWM_FREQUENCY = 8000  # Hz, must be between 100Hz and 10000Hz on Pico

# Maximum brightness value the hardware supports
# Pi Pico W uses 16-bit PWM, so max value is 2^16 - 1
MAX_DUTY_CYCLE = 65535

# Gamma correction exponent for LED brightness
# 2.2 is the standard for matching human brightness perception
GAMMA_CORRECTION = 2.2

# =============================================================================
# GPIO Pin Configuration
# =============================================================================
# Must be PWM-capable pins on the Pico W
WARM_LED_PIN = 10  # Pin for controlling warm white LEDs
COOL_LED_PIN = 20  # Pin for controlling cool white LEDs

# =============================================================================
# Transition Control Parameters (Legacy)
# =============================================================================
# Multiplier used to calculate number of steps in brightness transitions
# Higher values = smoother transitions but more CPU usage
STEPS_MULTIPLIER = 100  # 100 steps per full brightness change

# Maximum number of steps allowed in any transition
# Limits CPU usage for large brightness changes
MAX_STEPS = 200  # Caps transition steps at 200

# =============================================================================
# Night Light Mode
# =============================================================================
# Default brightness for night light mode (0.0-1.0)
NIGHT_LIGHT_BRIGHTNESS = 0.25  # 25% brightness
NIGHT_LIGHT_COOL = 0.0  # Cool LEDs off in night light mode

# =============================================================================
# NTP Configuration
# =============================================================================
# NTP Servers - tried in sequence for time synchronization
# Multiple servers provide redundancy if one is unavailable
NTP_SERVERS = [
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com"
]

# =============================================================================
# Timing Configuration
# =============================================================================
UPDATE_INTERVAL_MS = 5000       # LED update timer interval in milliseconds (5 seconds)
SCHEDULE_REFRESH_HOURS = 6      # Hours between schedule refreshes from server
WIFI_TIMEOUT_S = 30             # WiFi connection timeout in seconds
HTTP_TIMEOUT_S = 10             # HTTP request timeout in seconds
NTP_TIMEOUT_S = 5               # NTP request timeout in seconds

# Time past last schedule entry before considering it stale (seconds)
SCHEDULE_STALE_THRESHOLD_S = 3600  # 1 hour

# Default schedule mode when none is specified
DEFAULT_SCHEDULE_MODE = "dayNight"

# =============================================================================
# Demo Mode Configuration
# =============================================================================
# Total duration for a complete demo cycle (seconds)
DEMO_CYCLE_DURATION_S = 15

# Demo mode schedule entries (simulates a full day/night cycle)
# Each entry is (seconds_offset, warm_brightness_pct, cool_brightness_pct, label)
DEMO_SCHEDULE = [
    (0, 10, 0, "night"),           # Start: dim warm light
    (2, 25, 0, "pre_dawn"),        # Pre-dawn: slightly brighter
    (4, 60, 20, "dawn"),           # Dawn: warming up
    (6, 100, 80, "sunrise"),       # Sunrise: bright and warm
    (8, 90, 100, "midday"),        # Midday: peak brightness, cooler
    (10, 80, 50, "afternoon"),     # Afternoon: starting to warm
    (12, 50, 10, "sunset"),        # Sunset: warm glow
    (14, 20, 0, "dusk"),           # Dusk: dim warm
    (15, 10, 0, "night_end"),      # End: back to night
]

# =============================================================================
# HTTP Retry Configuration
# =============================================================================
HTTP_MAX_RETRIES = 3            # Number of retry attempts for HTTP requests
HTTP_BASE_DELAY_S = 1           # Base delay for exponential backoff (1, 2, 4, ...)

# =============================================================================
# API Configuration
# =============================================================================
SCHEDULE_API_URL = "https://api.example.com/lights"
SCHEDULE_API_TOKEN = "your_schedule_api_token"
LOGGING_API_URL = "https://api.example.com/logging"
LOGGING_API_TOKEN = "your_logging_api_token"
