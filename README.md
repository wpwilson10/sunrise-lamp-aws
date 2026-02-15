# Sunrise Lamp Controller

MicroPython-based smart lighting system that simulates natural daylight cycles using warm and cool LED channels. Designed for Raspberry Pi Pico W with cloud-based scheduling and logging.

## Description

This project creates a biologically-friendly lighting system that mimics natural daylight patterns. It manages dual-channel LED lighting (warm and cool white) to simulate the color temperature changes throughout the day, from pre-dawn through sunset and into night.

The system uses a modular architecture with clear separation of concerns:

- **LED Driver** - PWM control with gamma correction and brightness state tracking
- **Network Manager** - WiFi connectivity, NTP time sync, HTTP with retry logic
- **Schedule Manager** - Fetches, caches, and validates lighting schedules
- **Transition Engine** - Smooth brightness interpolation between schedule entries
- **Lamp Controller** - Orchestrates startup sequence and timer-based updates

The controller fetches dynamic lighting schedules from a cloud API, allowing for seasonal adjustments and custom scheduling. All events are logged to AWS for monitoring and debugging.

### Features

-   **Dynamic Light Control**

  - Smooth transitions between lighting states
  - Gamma-corrected PWM brightness control (γ = 2.2)
  - Dual-channel warm/cool LED management
  - Internal brightness state tracking prevents sudden jumps
  - IEEE 1789-2015 compliant PWM frequency

-   **Multiple Operating Modes**

  - `dayNight`: Follows natural daylight patterns
  - `scheduled`: User-defined custom schedules (works on Pico side but has no frontend UI currently)
  - `demo`: Quick 15-second demonstration cycle
  - Automatic night light fallback for safety

- **Reliable Network Operations**

  - Automatic retry with exponential backoff (1s, 2s, 4s)
  - Multiple NTP server fallback for time sync
  - WiFi reconnection handling
  - Graceful degradation when offline

-   **Smart Scheduling**

  - Cloud-based schedule management
  - Automatic schedule refresh (configurable, default 6 hours)
  - Timezone and DST handling via UTC offset
  - Linear interpolation for imperceptible brightness steps
  - Supports multiple daily events:
    - Civil twilight transitions
    - Sunrise/sunset simulation
    - Custom bed time dimming
    - Night light mode

-   **Cloud Integration**
    -   RESTful API for schedule updates
    -   AWS Lambda-based event logging
    -   Error reporting and monitoring
    -   Status tracking and debugging

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Lamp Controller                          │
│                    (main.py - orchestrator)                  │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ LED Driver  │  │ Transition  │  │  Schedule Manager   │  │
│  │             │◄─┤   Engine    │◄─┤                     │  │
│  │ PWM control │  │             │  │ Fetch, cache,       │  │
│  │ Gamma corr. │  │ Interpolate │  │ validate schedules  │  │
│  └─────────────┘  └─────────────┘  └──────────┬──────────┘  │
│                                               │              │
│                                    ┌──────────▼──────────┐  │
│                                    │  Network Manager    │  │
│                                    │                     │  │
│                                    │ WiFi, NTP, HTTP     │  │
│                                    │ Retry logic         │  │
│                                    └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## File Structure

```
├── main.py              # Entry point and LampController class
├── led_driver.py        # PWM control and brightness management
├── network_manager.py   # WiFi, NTP, and HTTP operations
├── schedule_manager.py  # Schedule fetching and caching
├── transition_engine.py # Brightness interpolation
├── models.py            # Data models for schedule entries
├── config.py            # Configuration (copy from template)
├── config.template.py   # Configuration template
└── tests/               # Property-based and unit tests
```

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
SCHEDULE_API_URL = "your_schedule_api"
SCHEDULE_API_TOKEN = "your_api_token"
LOGGING_API_URL = "your_logging_endpoint"
LOGGING_API_TOKEN = "your_logging_token"

# Hardware Configuration
WARM_LED_PIN = 10  # PWM capable GPIO
COOL_LED_PIN = 20  # PWM capable GPIO
```

Optional settings to tune behavior:

| Setting | Default | Description |
|---------|---------|-------------|
| `PWM_FREQUENCY` | 8000 | LED refresh rate in Hz |
| `UPDATE_INTERVAL_MS` | 5000 | Brightness update interval (ms) |
| `SCHEDULE_REFRESH_HOURS` | 6 | Hours between schedule fetches |
| `NIGHT_LIGHT_BRIGHTNESS` | 0.25 | Fallback brightness (0.0-1.0) |
| `NTP_SERVERS` | pool.ntp.org, time.google.com, time.cloudflare.com | NTP servers to try |
| `WIFI_TIMEOUT_S` | 30 | WiFi connection timeout |
| `HTTP_MAX_RETRIES` | 3 | Retry attempts for HTTP requests |

### Pi Pico Installation

Use [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) to upload files to the microcontroller over USB:

```bash
# Install mpremote (in the project venv)
uv pip install mpremote

# Connect Pico W via USB, then upload all source files
mpremote cp main.py led_driver.py network_manager.py schedule_manager.py transition_engine.py models.py config.py :

# Restart the Pico to run the new code
mpremote reset
```

Other useful commands:

```bash
mpremote ls :              # List files on the Pico
mpremote cat :main.py      # View a file on the Pico
mpremote rm :config.py     # Remove a file from the Pico
mpremote connect list      # List connected devices
mpremote repl              # Open interactive REPL (Ctrl+] to exit)
```

For first-time MicroPython setup, see the [getting started guide](https://projects.raspberrypi.org/en/projects/getting-started-with-the-pico/2). If the Pico doesn't have MicroPython firmware installed, hold the BOOTSEL button while plugging in USB, then drag the `.uf2` firmware file to the mounted drive.

### Demo Mode

Run the lamp in demo mode to test hardware without network connectivity:

```bash
# On desktop Python (for testing)
python main.py --demo

# On Pico, modify main.py to call run_demo_mode() instead of run_normal_mode()
```

Demo mode runs a 15-second cycle simulating a full day/night sequence, looping continuously.

To get the typings module to work:

1. Install [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) on the dev machine.
2. On the dev machine, run the commands to install the code from [this repo](https://github.com/Josverl/micropython-stubs/tree/main/mip)
   `mpremote mip install github:josverl/micropython-stubs/mip/typing.mpy`

### VSCode

The VSCode configuration is not strictly necessary but helps a bit with development experience.

For VSCode typings and error checking to work correctly with MicroPython, setup a venv and the type stubs using the Pylance options described [here](https://micropython-stubs.readthedocs.io/en/main/index.html).

The requirements-dev.txt is a recommended house keeping file from that process. The .vscode folder contains the VSCode workspace setting overrides.

## API Contract

The schedule API returns a unified JSON format with pre-computed Unix timestamps:

```json
{
  "mode": "dayNight",
  "serverTime": 1706745600,
  "brightnessSchedule": [
    { "time": "06:30", "unixTime": 1706785800, "warmBrightness": 25, "coolBrightness": 0, "label": "civil_twilight_begin" },
    { "time": "07:00", "unixTime": 1706787600, "warmBrightness": 75, "coolBrightness": 100, "label": "sunrise" },
    { "time": "19:30", "unixTime": 1706832600, "warmBrightness": 75, "coolBrightness": 100, "label": "sunset" },
    { "time": "20:00", "unixTime": 1706834400, "warmBrightness": 100, "coolBrightness": 0, "label": "civil_twilight_end" },
    { "time": "23:00", "unixTime": 1706845200, "warmBrightness": 100, "coolBrightness": 0, "label": "bed_time" },
    { "time": "23:30", "unixTime": 1706847000, "warmBrightness": 25, "coolBrightness": 0, "label": "night_time" }
  ]
}
```

See `light-schedule-service/docs/api_contract.md` for full documentation.

## Issues

When the Pi Pico gets stuck in a bootloop or otherwise refuses to connect, use the [flash_nuke.uf2](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html#resetting-flash-memory) option to clear the memory.

### Common Issues

- **Time sync fails**: Check WiFi connectivity. The lamp will stay in night light mode until NTP sync succeeds.
- **Schedule not updating**: Verify API URL and token. Check AWS logs for errors.
- **Sudden brightness jumps**: This was fixed in the refactor. The LED driver now tracks internal brightness state.
