"""Main module for the Sunrise Lamp Controller.

This module contains the LampController class that orchestrates all components
and manages the lamp's operation lifecycle.

Startup Sequence:
----------------
1. Set LEDs to night light mode (safe fallback)
2. Connect to WiFi (with timeout)
3. Sync time via NTP (required for schedule evaluation)
4. Fetch lighting schedule from server
5. Start periodic timer for brightness updates

The lamp always starts in night light mode to provide immediate illumination
while network operations complete. This ensures the lamp is never dark during
startup, even if network services are unavailable.

Timer-Based Execution:
---------------------
The controller uses a periodic timer (default 5 seconds) to:
1. Check if schedule needs refresh
2. Calculate current brightness target via TransitionEngine
3. Apply brightness to LEDs

This non-blocking approach ensures smooth transitions and responsive
schedule updates without blocking sleep calls.
"""

from __future__ import annotations

import time
import json

try:
    import machine
    from machine import Timer
except ImportError:
    machine = None
    Timer = None

import config
from led_driver import LEDDriver
from network_manager import NetworkManager
from schedule_manager import ScheduleManager
from transition_engine import TransitionEngine


class LampController:
    """Main controller orchestrating all lamp components.

    Manages the lifecycle of the lamp including startup, periodic updates,
    and error recovery. Coordinates between LED driver, network manager,
    schedule manager, and transition engine.

    Attributes:
        _leds: LED driver for controlling brightness
        _network: Network manager for WiFi and HTTP
        _schedule: Schedule manager for fetching and caching schedules
        _transition: Transition engine for interpolating brightness
        _timer: Periodic timer for updates
        _startup_complete: Whether startup sequence completed successfully
    """

    def __init__(self) -> None:
        """Initialize all components from configuration."""
        # Initialize LED driver first for immediate night light
        self._leds = LEDDriver(
            warm_pin=config.WARM_LED_PIN,
            cool_pin=config.COOL_LED_PIN,
            pwm_freq=config.PWM_FREQUENCY
        )

        # Initialize network manager
        self._network = NetworkManager(
            ssid=config.WIFI_SSID,
            password=config.WIFI_PASSWORD,
            ntp_servers=config.NTP_SERVERS
        )

        # Initialize schedule manager
        self._schedule = ScheduleManager(
            network=self._network,
            api_url=config.SCHEDULE_API_URL,
            api_token=config.SCHEDULE_API_TOKEN,
            refresh_hours=config.SCHEDULE_REFRESH_HOURS
        )

        # Initialize transition engine
        self._transition = TransitionEngine(
            schedule_manager=self._schedule,
            led_driver=self._leds
        )

        # Timer for periodic updates
        self._timer = None
        self._startup_complete = False

    def _log(self, message: str, level: str = "INFO") -> None:
        """Log a message to console and optionally to AWS.

        Args:
            message: Log message string
            level: Log level (DEBUG, INFO, ERROR)
        """
        print(f"{level} | {message}")

        # Attempt to send to AWS logging endpoint if connected
        if self._network.is_connected():
            headers = {
                "content-type": "application/json",
                "x-custom-auth": config.LOGGING_API_TOKEN
            }
            payload: dict = {
                "message": message,
                "level": level,
                "service_name": config.LOGGING_SERVICE_NAME,
                "client_name": config.CLIENT_NAME
            }
            # Fire and forget - don't block on logging
            self._network.http_post(config.LOGGING_API_URL, payload, headers=headers)

    def _startup_sequence(self) -> bool:
        """Execute startup: night light -> WiFi -> NTP -> schedule.

        Each phase is logged for debugging. If any phase fails, the lamp
        continues in night light mode until the next retry opportunity.

        Returns:
            bool: True if all phases completed successfully, False otherwise
        """
        # Phase 1: Set night light immediately
        self._log("Startup Phase 1: Setting night light mode", "DEBUG")
        self._leds.night_light(config.NIGHT_LIGHT_BRIGHTNESS)
        self._log("Night light active", "INFO")

        # Phase 2: Connect to WiFi
        self._log("Startup Phase 2: Connecting to WiFi", "DEBUG")
        if not self._network.connect_wifi(timeout=config.WIFI_TIMEOUT_S):
            self._log(f"WiFi connection failed after {config.WIFI_TIMEOUT_S}s timeout", "ERROR")
            return False
        self._log(f"WiFi connected to {config.WIFI_SSID}", "INFO")

        # Phase 3: Sync time via NTP
        self._log("Startup Phase 3: Syncing time via NTP", "DEBUG")
        if not self._network.sync_time():
            self._log("NTP time sync failed - cannot evaluate schedule times", "ERROR")
            return False
        self._log("NTP time sync successful", "INFO")

        # Phase 4: Fetch schedule
        self._log("Startup Phase 4: Fetching lighting schedule", "DEBUG")
        if not self._schedule.fetch_schedule():
            self._log("Schedule fetch failed - staying in night light mode", "ERROR")
            return False
        self._log(f"Schedule fetched: mode={self._schedule.get_mode()}", "INFO")

        # Phase 5: Apply current brightness from schedule
        self._log("Startup Phase 5: Applying initial brightness", "DEBUG")
        self._transition.update()
        self._log("Startup sequence complete", "INFO")

        self._startup_complete = True
        return True

    def _on_timer(self, timer: Timer) -> None:
        """Timer callback - update brightness and check schedule refresh.

        Called periodically by the timer. Handles:
        1. Schedule refresh if needed
        2. Brightness calculation and application
        3. Exception handling with night light fallback

        Args:
            timer: Timer object (passed by MicroPython timer callback)
        """
        try:
            # Check if we need to refresh the schedule
            if self._schedule.needs_refresh():
                self._log("Schedule refresh needed", "DEBUG")

                # Ensure WiFi is connected before fetching
                if self._network.ensure_connected():
                    if self._schedule.fetch_schedule():
                        self._log(f"Schedule refreshed: mode={self._schedule.get_mode()}", "INFO")
                    else:
                        self._log("Schedule refresh failed - using cached schedule", "ERROR")
                else:
                    self._log("WiFi reconnection failed - using cached schedule", "ERROR")

            # Update brightness based on current schedule position
            self._transition.update()

        except Exception as e:
            # On any error, fall back to night light mode
            self._log(f"Timer callback error: {e} - falling back to night light", "ERROR")
            try:
                self._leds.night_light(config.NIGHT_LIGHT_BRIGHTNESS)
            except:
                pass  # Last resort - can't do anything if LED control fails

    def start(self) -> None:
        """Start the lamp controller.

        Executes the startup sequence and sets up the periodic timer.
        This method blocks indefinitely (timer runs in background on Pico).
        """
        self._log("Lamp Controller starting", "INFO")

        # Run startup sequence
        self._startup_sequence()

        # Set up periodic timer for brightness updates
        if machine is not None:
            self._timer = machine.Timer()
            self._timer.init(
                period=config.UPDATE_INTERVAL_MS,
                mode=machine.Timer.PERIODIC,
                callback=self._on_timer
            )
            self._log(f"Timer started with {config.UPDATE_INTERVAL_MS}ms interval", "INFO")
        else:
            self._log("Running in desktop mode - no timer available", "INFO")

    def stop(self) -> None:
        """Stop the lamp controller and clean up resources."""
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None
        self._leds.off()
        self._log("Lamp Controller stopped", "INFO")

    def run_demo(self) -> None:
        """Run demo mode locally without network connectivity.

        This sets up the demo schedule directly and runs the normal
        update loop, demonstrating the lamp's brightness transitions
        without needing a server connection.

        The demo shows a 15-second simulation of a full day/night cycle:
        - Night (dim warm)
        - Pre-dawn (slightly brighter)
        - Dawn (warming up)
        - Sunrise (bright and warm)
        - Midday (peak brightness, cooler)
        - Afternoon (starting to warm)
        - Sunset (warm glow)
        - Dusk (dim warm)
        - Night (back to start)

        The cycle loops continuously until interrupted.
        """
        self._log("Starting demo mode (no network)", "INFO")

        # Set up demo schedule directly without fetching from server
        self._schedule._mode = "demo"
        if not self._schedule._setup_demo_schedule():
            self._log("Failed to set up demo schedule", "ERROR")
            return

        cycle_duration = config.DEMO_CYCLE_DURATION_S
        self._log(f"Demo: {cycle_duration}s cycle, looping continuously", "INFO")

        # Run the demo loop with frequent updates for smooth transitions
        update_interval_s = 0.05  # 50ms updates

        try:
            while True:
                # Refresh the demo schedule periodically to keep timestamps current
                if self._schedule.needs_refresh():
                    self._schedule._setup_demo_schedule()

                # Update brightness using the normal transition engine
                self._transition.update()
                time.sleep(update_interval_s)

        except KeyboardInterrupt:
            self._log("Demo mode interrupted", "INFO")
            self._leds.off()


def run_demo_mode() -> None:
    """Run the lamp in demo mode (no network required)."""
    controller = LampController()
    controller.run_demo()


def run_normal_mode() -> None:
    """Run the lamp in normal operation mode."""
    controller = None
    try:
        controller = LampController()
        controller.start()

        # Keep main thread alive (timer runs in background)
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        if controller:
            controller._log("System stopping due to keyboard interrupt", "INFO")
            controller.stop()
        if machine is not None:
            machine.reset()

    except Exception as e:
        if controller:
            controller._log(f"Fatal error: {e}", "ERROR")
            controller._leds.night_light(config.NIGHT_LIGHT_BRIGHTNESS)
        else:
            print(f"ERROR | Fatal error during initialization: {e}")


# Main entry point
if __name__ == "__main__":
    import sys

    # Check for demo mode flag
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        run_demo_mode()
    else:
        run_normal_mode()
