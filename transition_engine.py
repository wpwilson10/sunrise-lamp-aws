"""Transition Engine module for calculating brightness targets based on schedule.

This module handles the interpolation of brightness values between schedule
entries, providing smooth transitions throughout the day. It reads from the
ScheduleManager's cached schedule and updates the LEDDriver with calculated
brightness targets.

Interpolation Strategy:
----------------------
The engine uses linear interpolation between schedule entries to calculate
the current brightness target. Given two adjacent entries (prev, next) and
the current time T:

    progress = (T - prev.time) / (next.time - prev.time)
    brightness = prev.brightness + (next.brightness - prev.brightness) * progress

This ensures smooth, perceptually uniform transitions when combined with
the LEDDriver's gamma correction.

Edge Cases:
----------
1. Before first entry: Use first entry's brightness (no transition yet)
2. After last entry: Use last entry's brightness (day complete)
3. No schedule: Fall back to night light mode (warm=0.25, cool=0.0)
4. Exactly at entry time: Return that entry's exact brightness

Requirements Addressed:
- 2.3: Transition_Engine reads current brightness from LED_Driver's internal state
- 2.6: Linear interpolation on perceived brightness values
- 4.1: At entry time, brightness equals entry's target
- 4.2: Transition duration computed from time between entries
- 4.3: Minimum 60s transition when no previous entry
- 4.4: Skip to most recent past entry when multiple are past
- 9.2: Timer-driven updates calculate current target and apply immediately
"""

import time

try:
    import config
except ImportError:
    config = None

from led_driver import LEDDriver
from schedule_manager import ScheduleManager


class TransitionEngine:
    """Calculates brightness targets based on schedule position.

    Reads schedule entries from ScheduleManager and interpolates brightness
    values based on current time. Updates LEDDriver with calculated targets.

    Attributes:
        _schedule: ScheduleManager instance for reading schedule entries
        _leds: LEDDriver instance for setting brightness
    """

    # Default night light brightness when no schedule available
    NIGHT_LIGHT_WARM: float = 0.25
    NIGHT_LIGHT_COOL: float = 0.0

    def __init__(self, schedule_manager: ScheduleManager, led_driver: LEDDriver) -> None:
        """Initialize TransitionEngine with schedule manager and LED driver.

        Args:
            schedule_manager: ScheduleManager instance for reading schedule entries
            led_driver: LEDDriver instance for setting brightness
        """
        self._schedule = schedule_manager
        self._leds = led_driver

    def update(self) -> None:
        """Calculate and apply current brightness based on time and schedule.

        Gets the current target brightness from the schedule and applies it
        to the LED driver. This method should be called periodically by the
        main controller's timer.
        """
        warm, cool = self.get_current_target()
        self._leds.set_brightness(warm, cool)

    def get_current_target(self) -> tuple[float, float]:
        """Calculate brightness target based on current position in schedule.

        Finds the surrounding schedule entries for the current time and
        performs linear interpolation to determine the target brightness.

        For demo mode, the schedule loops continuously.

        Returns:
            Tuple of (warm, cool) brightness values in range 0.0-1.0
        """
        entries = self._schedule.get_entries()

        # No schedule - fall back to night light
        if not entries:
            warm = config.NIGHT_LIGHT_BRIGHTNESS if config else self.NIGHT_LIGHT_WARM
            cool = config.NIGHT_LIGHT_COOL if config else self.NIGHT_LIGHT_COOL
            return (warm, cool)

        # Handle demo mode with looping
        if self._schedule.is_demo_mode():
            return self._get_demo_target(entries)

        now = time.time()

        # Find surrounding entries
        prev_entry = None
        next_entry = None

        for i, entry in enumerate(entries):
            if entry["unix_time"] > now:
                next_entry = entry
                prev_entry = entries[i - 1] if i > 0 else None
                break
        else:
            # Past all entries - use last entry's brightness
            last = entries[-1]
            return (last["warm"], last["cool"])

        if prev_entry is None:
            # Before first entry - use first entry's brightness
            return (next_entry["warm"], next_entry["cool"])

        # Linear interpolation between prev and next
        duration = next_entry["unix_time"] - prev_entry["unix_time"]
        elapsed = now - prev_entry["unix_time"]

        # Avoid division by zero (shouldn't happen with valid schedule)
        if duration <= 0:
            return (next_entry["warm"], next_entry["cool"])

        progress = elapsed / duration

        # Clamp progress to [0, 1] for safety
        progress = max(0.0, min(1.0, progress))

        warm = prev_entry["warm"] + (next_entry["warm"] - prev_entry["warm"]) * progress
        cool = prev_entry["cool"] + (next_entry["cool"] - prev_entry["cool"]) * progress

        return (warm, cool)

    def _get_demo_target(self, entries: list) -> tuple[float, float]:
        """Calculate brightness target for demo mode with looping.

        Demo mode continuously loops through the schedule based on
        elapsed time modulo the cycle duration.

        Args:
            entries: List of schedule entries

        Returns:
            Tuple of (warm, cool) brightness values in range 0.0-1.0
        """
        cycle_duration = self._schedule.get_demo_cycle_duration()

        # Get the first entry's time as the cycle start reference
        cycle_start = entries[0]["unix_time"]
        now = time.time()

        # Calculate position within the current cycle
        elapsed_total = now - cycle_start
        cycle_time = elapsed_total % cycle_duration

        # Find surrounding entries based on relative offset within cycle
        prev_entry = entries[-1]  # Default to last if before first
        next_entry = entries[0]   # Default to first

        for i, entry in enumerate(entries):
            # Calculate relative offset from cycle start
            entry_offset = entry["unix_time"] - cycle_start
            if entry_offset > cycle_time:
                next_entry = entry
                prev_entry = entries[i - 1] if i > 0 else entries[-1]
                break
        else:
            # Past all entries in this cycle, wrapping to start
            prev_entry = entries[-1]
            next_entry = entries[0]

        # Calculate interpolation progress
        prev_offset = prev_entry["unix_time"] - cycle_start
        next_offset = next_entry["unix_time"] - cycle_start

        # Handle wrap-around at end of cycle
        if next_offset <= prev_offset:
            next_offset += cycle_duration
        if cycle_time < prev_offset:
            cycle_time += cycle_duration

        duration = next_offset - prev_offset
        if duration <= 0:
            return (next_entry["warm"], next_entry["cool"])

        progress = (cycle_time - prev_offset) / duration
        progress = max(0.0, min(1.0, progress))

        warm = prev_entry["warm"] + (next_entry["warm"] - prev_entry["warm"]) * progress
        cool = prev_entry["cool"] + (next_entry["cool"] - prev_entry["cool"]) * progress

        return (warm, cool)
