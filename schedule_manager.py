"""Schedule Manager module for fetching, caching, and managing lighting schedules.

This module handles schedule data from the server, computes unix timestamps from
time strings, validates brightness values, and determines when schedules need
to be refreshed.

Schedule Data Flow:
------------------
1. Server provides schedule with mode, UTC offset, and entries (time strings + brightness)
2. ScheduleManager fetches via NetworkManager
3. Time strings ("HH:MM") are converted to unix timestamps using current date + UTC offset
4. Entries are sorted chronologically and cached
5. TransitionEngine reads cached entries to interpolate brightness

Timezone Handling:
-----------------
The Pico's RTC is set to UTC via NTP. Schedule times from the server are in local
time (e.g., "07:00" for sunrise). We need to convert these to UTC unix timestamps:

1. Server provides utc_offset (e.g., -18000 for EST = UTC-5)
2. We compute local timestamp for "HH:MM" on today's date
3. We subtract utc_offset to get UTC timestamp

Example: "07:00" EST (UTC-5)
- Local timestamp for 07:00 today
- utc_offset = -18000 (5 hours in seconds)
- UTC timestamp = local_timestamp - (-18000) = local_timestamp + 18000
- So 07:00 EST = 12:00 UTC

Refresh Strategy:
----------------
Schedules are refreshed when:
1. No schedule exists (first boot or cache cleared)
2. Current time exceeds last entry by >1 hour (schedule is stale)
3. Configurable refresh interval elapsed (default 6 hours)

This balances freshness with network efficiency.
"""

from __future__ import annotations

import time

try:
    import config
except ImportError:
    config = None

from network_manager import NetworkManager


# ScheduleEntry dict structure (for documentation):
# {
#     "unix_time": int,   # Unix timestamp
#     "warm": float,      # 0.0-1.0 brightness
#     "cool": float,      # 0.0-1.0 brightness
#     "label": str        # Optional label
# }


class ScheduleManager:
    """Manages schedule fetching, caching, and timestamp computation.

    Fetches lighting schedules from the server, converts time strings to
    unix timestamps, validates brightness values, and caches the result
    for use by the TransitionEngine.

    Attributes:
        _network: NetworkManager instance for HTTP requests
        _api_url: URL endpoint for fetching schedules
        _api_token: Authentication token for API requests
        _refresh_hours: Hours between schedule refreshes
        _cached_schedule: List of processed schedule entries
        _utc_offset: Seconds from UTC
        _last_fetch_time: Unix timestamp of last successful fetch
        _mode: Current schedule mode
    """

    # Default refresh interval in hours
    DEFAULT_REFRESH_HOURS: int = 6

    # Time past last entry before considering schedule stale (seconds)
    STALE_THRESHOLD: int = 3600  # 1 hour

    # Default schedule mode
    DEFAULT_MODE: str = "dayNight"

    def __init__(
        self,
        network: NetworkManager,
        api_url: str,
        api_token: str,
        refresh_hours: int | None = None
    ) -> None:
        """Initialize ScheduleManager with network manager and API configuration.

        Args:
            network: NetworkManager instance for HTTP requests
            api_url: URL endpoint for fetching schedules
            api_token: Authentication token for API requests
            refresh_hours: Hours between schedule refreshes (default 6)
        """
        self._network = network
        self._api_url = api_url
        self._api_token = api_token
        self._refresh_hours = refresh_hours or self.DEFAULT_REFRESH_HOURS

        # Internal state
        self._cached_schedule = None  # List of schedule entries with unix_time
        self._utc_offset = 0  # Seconds from UTC (e.g., -18000 for EST)
        self._last_fetch_time = 0  # Unix timestamp of last successful fetch

        # Use config value or fallback to class default
        default_mode = config.DEFAULT_SCHEDULE_MODE if config else self.DEFAULT_MODE
        self._mode = default_mode  # Current schedule mode

    def _validate_brightness(self, value: Any) -> bool:
        """Validate that brightness value is within 0-100 range.

        Args:
            value: Brightness value to validate

        Returns:
            bool: True if valid (0-100), False otherwise
        """
        try:
            num = int(value) if not isinstance(value, (int, float)) else value
            return 0 <= num <= 100
        except (ValueError, TypeError):
            return False

    def _compute_timestamps(
        self,
        entries: list[dict],
        utc_offset: int
    ) -> list[dict]:
        """Convert time strings to unix timestamps using current date and offset.

        Takes schedule entries with "HH:MM" time strings and converts them to
        unix timestamps for today's date, adjusted for timezone.

        Args:
            entries: List of dicts with 'time', 'warm'/'warmBrightness',
                    'cool'/'coolBrightness' keys
            utc_offset: Seconds from UTC (negative for west of UTC)

        Returns:
            List of dicts with 'unix_time', 'warm', 'cool', 'label' keys,
            sorted chronologically. Invalid entries are skipped.
        """
        now = time.time()
        today = time.localtime(now)

        result: list[dict] = []
        for entry in entries:
            try:
                # Parse time string
                time_str = entry.get("time", "")
                if ":" not in time_str:
                    print(f"Invalid time format: {time_str}")
                    continue

                parts = time_str.split(":")
                h = int(parts[0])
                m = int(parts[1])

                if not (0 <= h <= 23 and 0 <= m <= 59):
                    print(f"Invalid time values: {time_str}")
                    continue

                # Get brightness values (support both naming conventions)
                warm = entry.get("warm", entry.get("warmBrightness", 0))
                cool = entry.get("cool", entry.get("coolBrightness", 0))

                # Validate brightness values
                if not self._validate_brightness(warm) or not self._validate_brightness(cool):
                    print(f"Invalid brightness values: warm={warm}, cool={cool}")
                    continue

                # Create timestamp for today at this time (local time)
                # MicroPython time.mktime expects an 8-element tuple:
                # (year, month, mday, hour, min, sec, wday, yday)
                local_time = time.mktime((
                    today[0],  # year
                    today[1],  # month
                    today[2],  # day
                    h,         # hour
                    m,         # minute
                    0,         # second
                    0,         # weekday (ignored by mktime)
                    0          # yearday (ignored by mktime)
                ))

                # Adjust for timezone
                # If utc_offset is -18000 (EST = UTC-5), local 07:00 = UTC 12:00
                # unix_time = local_time - utc_offset
                unix_time = int(local_time - utc_offset)

                result.append({
                    "unix_time": unix_time,
                    "warm": float(warm) / 100.0,  # Convert 0-100 to 0.0-1.0
                    "cool": float(cool) / 100.0,
                    "label": entry.get("label", "")
                })

            except (ValueError, KeyError, TypeError) as e:
                print(f"Error processing entry {entry}: {e}")
                continue

        # Sort by unix_time
        result.sort(key=lambda x: x["unix_time"])
        return result

    def fetch_schedule(self) -> bool:
        """Fetch new schedule from server and update cache.

        Makes HTTP GET request to the schedule API, parses the response,
        computes timestamps, and updates the cached schedule.

        If the server returns mode="demo", the demo schedule from config
        is used instead of server-provided entries.

        Returns:
            bool: True if schedule was fetched and cached successfully,
                  False on any error.
        """
        headers = {"x-custom-auth": self._api_token}

        response = self._network.http_get(self._api_url, headers=headers)

        if response is None:
            print("Failed to fetch schedule from server")
            return False

        try:
            # Extract mode
            default_mode = config.DEFAULT_SCHEDULE_MODE if config else self.DEFAULT_MODE
            self._mode = response.get("mode", default_mode)

            # If demo mode, use hardcoded demo schedule from config
            if self._mode == "demo":
                return self._setup_demo_schedule()

            # Extract UTC offset (default to 0 if missing)
            utc_offset = response.get("utc_offset", 0)
            if utc_offset is None:
                print("Warning: No UTC offset provided, defaulting to UTC")
                utc_offset = 0
            self._utc_offset = utc_offset

            # Get entries - support both 'entries' and 'schedule' keys
            entries = response.get("entries", response.get("schedule", []))

            if not entries:
                print("Warning: Empty schedule received")
                return False

            # Compute timestamps and validate
            computed = self._compute_timestamps(entries, utc_offset)

            if not computed:
                print("No valid entries after processing")
                return False

            # Update cache
            self._cached_schedule = computed
            self._last_fetch_time = int(time.time())

            print(f"Schedule fetched: {len(computed)} entries, mode={self._mode}")
            return True

        except Exception as e:
            print(f"Error parsing schedule response: {e}")
            return False

    def _setup_demo_schedule(self) -> bool:
        """Set up the demo schedule from config.

        Creates schedule entries based on the DEMO_SCHEDULE config,
        converting relative offsets to absolute unix timestamps.

        Returns:
            bool: True if demo schedule was set up successfully.
        """
        if not config:
            print("Config not available for demo mode")
            return False

        demo_schedule = getattr(config, 'DEMO_SCHEDULE', None)
        cycle_duration = getattr(config, 'DEMO_CYCLE_DURATION_S', 15)

        if not demo_schedule:
            print("No demo schedule configured")
            return False

        # Convert demo schedule to standard format with unix timestamps
        # Demo schedule loops continuously, so we create entries for the current cycle
        now = int(time.time())
        cycle_start = now  # Start the cycle now

        entries: list[dict] = []
        for offset, warm, cool, label in demo_schedule:
            entries.append({
                "unix_time": cycle_start + offset,
                "warm": float(warm) / 100.0,
                "cool": float(cool) / 100.0,
                "label": label
            })

        self._cached_schedule = entries
        self._last_fetch_time = now
        self._utc_offset = 0  # Demo mode uses local time

        print(f"Demo schedule set up: {len(entries)} entries, {cycle_duration}s cycle")
        return True

    def is_demo_mode(self) -> bool:
        """Check if currently in demo mode.

        Returns:
            bool: True if mode is "demo", False otherwise.
        """
        return self._mode == "demo"

    def get_demo_cycle_duration(self) -> int:
        """Get the demo cycle duration in seconds.

        Returns:
            int: Demo cycle duration from config, or 15 as default.
        """
        if config:
            return getattr(config, 'DEMO_CYCLE_DURATION_S', 15)
        return 15

    def needs_refresh(self) -> bool:
        """Check if schedule should be refreshed.

        Returns True if:
        - No schedule exists (cache is None or empty)
        - Current time exceeds last entry by more than 1 hour
        - Refresh interval has elapsed since last fetch

        Returns:
            bool: True if schedule should be refreshed, False otherwise
        """
        now = int(time.time())

        # Case (a): No schedule exists
        if self._cached_schedule is None or len(self._cached_schedule) == 0:
            return True

        # Case (b): Current time exceeds last entry by stale threshold
        stale_threshold = config.SCHEDULE_STALE_THRESHOLD_S if config else self.STALE_THRESHOLD
        last_entry_time = self._cached_schedule[-1]["unix_time"]
        if now > last_entry_time + stale_threshold:
            return True

        # Case (c): Refresh interval elapsed
        refresh_interval = self._refresh_hours * 3600  # Convert hours to seconds
        if now - self._last_fetch_time > refresh_interval:
            return True

        return False

    def get_entries(self) -> list[dict]:
        """Return cached schedule entries sorted by time.

        Returns:
            List of schedule entry dicts with 'unix_time', 'warm', 'cool', 'label',
            or empty list if no schedule cached.
        """
        if self._cached_schedule is None:
            return []
        return self._cached_schedule

    def get_mode(self) -> str:
        """Return current schedule mode.

        Returns:
            str: Mode string ('dayNight', 'scheduled', 'demo')
        """
        return self._mode

    def has_valid_schedule(self) -> bool:
        """Check if a valid cached schedule exists.

        Returns:
            bool: True if schedule is cached and non-empty, False otherwise
        """
        return self._cached_schedule is not None and len(self._cached_schedule) > 0

    def get_utc_offset(self) -> int:
        """Return the current UTC offset in seconds.

        Returns:
            int: UTC offset in seconds (negative for west of UTC)
        """
        return self._utc_offset

    def get_last_fetch_time(self) -> int:
        """Return the timestamp of the last successful fetch.

        Returns:
            int: Unix timestamp of last fetch, or 0 if never fetched
        """
        return self._last_fetch_time
