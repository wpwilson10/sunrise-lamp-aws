# Sunrise Lamp Controller

MicroPython-based smart lighting system that simulates natural daylight cycles using warm and cool LED channels. Designed for Raspberry Pi Pico W with cloud-based scheduling and logging.

## Description

This project creates a biologically-friendly lighting system that mimics natural daylight patterns. It manages dual-channel LED lighting (warm and cool white) to simulate the color temperature changes throughout the day, from pre-dawn through sunset and into night.

The system fetches dynamic lighting schedules from a cloud API, allowing for seasonal adjustments and custom scheduling. All events are logged to AWS for monitoring and debugging.

### Features

-   **Dynamic Light Control**

    -   Smooth transitions between lighting states
    -   Gamma-corrected PWM brightness control
    -   Dual-channel warm/cool LED management
    -   IEEE 1789-2015 compliant PWM frequency

-   **Multiple Operating Modes**

    -   `dayNight`: Follows natural daylight patterns
    -   `scheduled`: User-defined custom schedules
    -   `demo`: Quick demonstration cycle
    -   Fallback night light mode for safety

-   **Smart Scheduling**

    -   Cloud-based schedule management
    -   Automatic schedule updates
    -   Handles timezone and DST changes
    -   Supports multiple daily events:
        -   Civil twilight transitions
        -   Sunrise/sunset simulation
        -   Custom bed time dimming
        -   Night light mode

-   **Cloud Integration**
    -   RESTful API for schedule updates
    -   AWS Lambda-based event logging
    -   Error reporting and monitoring
    -   Status tracking and debugging

## Setup

### Hardware Requirements

-   Raspberry Pi Pico W
-   Warm white LED strip/array
-   Cool white LED strip/array
-   PWM-capable MOSFETs for LED control
-   12/24V power supply (sized for LED load)

### Configuration

1. Copy `config.template.py` to `config.py`
2. Configure required settings:

```python
# Network Settings
WIFI_SSID = "your_network"
WIFI_PASSWORD = "your_password"

# Cloud Integration
AWS_LOG_URL = "your_lambda_endpoint"
AWS_SECRET_TOKEN = "your_secret_token"
SCHEDULE_API_URL = "your_schedule_api"

# Hardware Configuration
WARM_LED_PIN = 10  # PWM capable GPIO
COOL_LED_PIN = 20  # PWM capable GPIO
```

Optional settings to tune behavior:

-   `PWM_FREQUENCY`: LED refresh rate (default 8000Hz)
-   `STEPS_PER_SECOND`: Transition smoothness (default 10 per second)
-   `MAX_STEPS`: Limits brightness transitions steps (default 2000 per transition)
-   `NIGHT_LIGHT_BRIGHTNESS`: Default safety light level (default 25%)

### Pi Pico Installation

Use Thonny to upload the main.py and config.py files to the microcontroller. Setup guide [here](https://projects.raspberrypi.org/en/projects/getting-started-with-the-pico/2). There are no good VSCode extensions at this time that can reliably connect and manage files.

To get the typings module to work:

1. Install [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) on the dev machine.
2. On the dev machine, run the commands to install the code from [this repo](https://github.com/Josverl/micropython-stubs/tree/main/mip)
   `mpremote mip install github:josverl/micropython-stubs/mip/typing.mpy`

### VSCode

The VSCode configuration is not strictly necessary but helps a bit with development experience.

For VSCode typings and error checking to work correctly with MicroPython, setup a venv and the type stubs using the Pylance options described [here](https://micropython-stubs.readthedocs.io/en/main/index.html).

The requirements-dev.txt is a recommended house keeping file from that process. The .vscode folder contains the VSCode workspace setting overrides.

## Issues

When the Pi Pico gets stuck in a bootloop or otherwise refuses to connect, use the [flash_nuke.uf2](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html#resetting-flash-memory) option to clear the memory.
