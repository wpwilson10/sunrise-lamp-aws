# Name of the client device for identification when logging
CLIENT_NAME = "Sunrise Lamp"  # Name of the device

# WiFi Credentials
WIFI_SSID = "wifi_name"  # Network name to connect to
WIFI_PASSWORD = "wifi_password"  # Network password

# PWM Settings
# IEEE 1789-2015 recommends PWM frequency > 3000Hz to prevent visible flicker
# We double this for safety margin and smooth operation
PWM_FREQUENCY = 8000  # Hz, must be between 100Hz and 10000Hz on Pico

# Maximum brightness value the hardware supports
# Pi Pico W uses 16-bit PWM, so max value is 2^16 - 1
MAX_DUTY_CYCLE = 65535

# GPIO pin numbers for LED control
# Must be PWM-capable pins on the Pico W
WARM_LED_PIN = 10  # Pin for controlling warm white LEDs
COOL_LED_PIN = 20  # Pin for controlling cool white LEDs

# How many fade updates to perform each second.
# Higher = smoother but slightly more CPU wakeups.
STEPS_PER_SECOND: int = 10

# Maximum number of steps allowed in any transition
# Limits CPU usage for large brightness changes
MAX_STEPS = 2000

# Default brightness for night light mode (0.0-1.0)
NIGHT_LIGHT_BRIGHTNESS = 0.25  # 25% brightness

# AWS Lambda Configuration
# URL endpoint for sending log messages
AWS_LOGGING_API = "https://api.example.com/logging"
# Authentication token for AWS Lambda logging
AWS_LOGGING_SECRET_TOKEN = "my_secret_token"
# URL endpoint for fetching lighting schedules
AWS_LIGHT_SCHEDULE_API = "https://api.example.com/lights"
# Authentication token for AWS Lambda light schedule
AWS_LIGHTS_SECRET_TOKEN = "my_secret_token"
