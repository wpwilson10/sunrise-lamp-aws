# WiFi Credentials
WIFI_SSID = "wifi_name"        # Network name to connect to
WIFI_PASSWORD = "wifi_password" # Network password

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

# Transition Control Parameters
# Multiplier used to calculate number of steps in brightness transitions
# Higher values = smoother transitions but more CPU usage
STEPS_MULTIPLIER = 100  # 100 steps per full brightness change

# Maximum number of steps allowed in any transition
# Limits CPU usage for large brightness changes
MAX_STEPS = 200  # Caps transition steps at 200

# Default brightness for night light mode (0.0-1.0)
NIGHT_LIGHT_BRIGHTNESS = 0.25  # 25% brightness

# AWS Lambda Configuration
# URL endpoint for sending log messages
AWS_LOG_URL = "https://xyz.lambda-url.us-east-1.on.aws/"
# Authentication token for AWS Lambda access
AWS_SECRET_TOKEN = "my_secure_static_token_12345"

# Schedule API Configuration
# URL endpoint for fetching lighting schedules
SCHEDULE_API_URL = "https://api.example.com/schedule"
# Authentication token for schedule API access
SCHEDULE_API_TOKEN = "your_auth_token"