# pyright: reportMissingModuleSource=false, reportUnknownMemberType=false
"""Network Manager module for WiFi, NTP, and HTTP operations.

This module encapsulates all network connectivity with retry logic and
fallback mechanisms for the Sunrise Lamp Controller running on Raspberry Pi Pico W.

Architecture Overview:
---------------------
The Pico W has NO battery-backed RTC (Real-Time Clock). When power is lost,
the internal software RTC resets to the Unix epoch (January 1, 1970). This means:
1. We MUST sync time via NTP after every power cycle
2. Schedule times cannot be evaluated until NTP sync succeeds
3. The lamp falls back to night light mode if time sync fails

NTP (Network Time Protocol):
---------------------------
NTP synchronizes clocks over a network. The protocol works by:
1. Client sends a request packet to an NTP server on UDP port 123
2. Server responds with a 48-byte packet containing timestamps
3. Client extracts the "transmit timestamp" (bytes 40-43) which is seconds
   since January 1, 1900 (NTP epoch)
4. We subtract NTP_DELTA (2,208,988,800 seconds) to convert to Unix epoch
   (seconds since January 1, 1970)
5. The Unix timestamp is then used to set the Pico's software RTC

We try multiple NTP servers in sequence because:
- Individual servers may be temporarily unavailable
- DNS resolution might fail for some hostnames
- Network routing issues can affect specific servers

RTC (Real-Time Clock) on Pico W:
-------------------------------
The Pico W's RTC is software-based and maintained by the RP2040 chip while
powered. The machine.RTC().datetime() method expects a tuple:
    (year, month, day, weekday, hour, minute, second, subsecond)
Note: weekday is 0=Monday through 6=Sunday, but we add 1 because the RTC
expects 1=Monday through 7=Sunday.

WiFi Reconnection Strategy:
--------------------------
WiFi connections can drop due to router restarts, signal issues, or power
management. This module provides:
1. Initial connection with configurable timeout
2. Connection status checking via is_connected()
3. Automatic reconnection via ensure_connected() which should be called
   before any network operation
4. The main controller should call ensure_connected() periodically or
   before schedule fetches

HTTP Retry Logic:
----------------
Network operations can fail transiently due to:
- Server overload or maintenance
- Temporary network congestion
- DNS resolution delays
- Socket timeouts

We use exponential backoff to avoid overwhelming servers:
- Attempt 1: immediate
- Attempt 2: wait 1 second
- Attempt 3: wait 2 seconds
- Attempt 4: wait 4 seconds (if we had 4 retries)

This gives the network/server time to recover between attempts.
"""

from typing import Any

import time
import json

try:
    import config
except ImportError:
    config = None

try:
    import network
    import socket
    import struct
    import machine
except ImportError:
    network = None
    socket = None
    struct = None
    machine = None

try:
    import urequests as requests  # MicroPython
except ImportError:
    try:
        import requests  # Desktop Python
    except ImportError:
        requests = None


class NetworkManager:
    """Manages network connectivity with retry and fallback logic.

    This class handles all network operations for the Sunrise Lamp:
    - WiFi connection and reconnection
    - NTP time synchronization (critical since Pico has no battery-backed RTC)
    - HTTP requests with automatic retry and exponential backoff

    Example usage:
        nm = NetworkManager(ssid="MyNetwork", password="secret")

        if nm.connect_wifi():
            if nm.sync_time():
                # RTC is now set, safe to evaluate schedule times
                schedule = nm.http_get("https://api.example.com/schedule")

    Attributes:
        _ssid: WiFi network name
        _password: WiFi network password
        _ntp_servers: List of NTP server hostnames to try
        _wlan: WLAN interface object
        _time_synced: Whether NTP sync has succeeded
        _last_retry_delays: List of delays used in last retry sequence (for testing)
    """

    # Default NTP servers to try in sequence.
    # Using multiple servers provides redundancy if one is unavailable.
    # pool.ntp.org is a load-balanced pool of volunteer NTP servers.
    DEFAULT_NTP_SERVERS: list[str] = [
        "pool.ntp.org",
        "time.google.com",
        "time.cloudflare.com"
    ]

    # NTP epoch offset: seconds between NTP epoch (1900) and Unix epoch (1970).
    # NTP timestamps are seconds since Jan 1, 1900.
    # Unix timestamps are seconds since Jan 1, 1970.
    # Difference: 70 years = 2,208,988,800 seconds
    NTP_DELTA: int = 2208988800

    # Retry configuration for HTTP requests (class defaults, can be overridden by config)
    MAX_RETRIES: int = 3
    BASE_DELAY: int = 1  # Base delay in seconds for exponential backoff (1, 2, 4, ...)

    def __init__(self, ssid: str, password: str, ntp_servers: list[str] | None = None) -> None:
        """Initialize NetworkManager with WiFi credentials.

        Args:
            ssid: WiFi network name (SSID) to connect to
            password: WiFi network password
            ntp_servers: Optional list of NTP server hostnames to try.
                        Defaults to pool.ntp.org, time.google.com, time.cloudflare.com

        Note:
            This does NOT automatically connect to WiFi. Call connect_wifi()
            after initialization to establish the connection.
        """
        self._ssid = ssid
        self._password = password
        self._ntp_servers = ntp_servers or self.DEFAULT_NTP_SERVERS
        self._wlan = None
        self._time_synced = False

        # For testing: track retry delays (used by property tests)
        self._last_retry_delays: list[float] = []

    def connect_wifi(self, timeout: int = 30) -> bool:
        """Connect to WiFi network with timeout.

        Activates the WLAN interface and attempts to connect to the configured
        network. Blocks until connected or timeout expires.

        Args:
            timeout: Maximum seconds to wait for connection (default 30).
                    30 seconds is usually enough for most networks, but slow
                    routers or congested networks may need more time.

        Returns:
            bool: True if connected successfully, False if timeout or error.

        Note:
            If already connected, returns True immediately without reconnecting.
            The Pico W has a single WLAN interface in station mode (STA_IF).
        """
        if network is None:
            # Desktop testing mode - no actual WiFi hardware
            return False

        try:
            # Initialize WLAN interface in station mode (client, not access point)
            self._wlan = network.WLAN(network.STA_IF)
            self._wlan.active(True)

            # Already connected? Return early.
            if self._wlan.isconnected():
                return True

            # Start connection attempt
            self._wlan.connect(self._ssid, self._password)

            # Poll for connection status until timeout
            start_time = time.time()
            while not self._wlan.isconnected():
                if time.time() - start_time > timeout:
                    print(f"WiFi connection timeout after {timeout}s")
                    return False
                time.sleep(0.5)  # Check every 500ms to balance responsiveness and CPU

            # Connection successful - log the assigned IP address
            ip_address: str = self._wlan.ifconfig()[0]
            print(f"Connected to WiFi '{self._ssid}'. IP: {ip_address}")
            return True

        except Exception as e:
            print(f"WiFi connection error: {e}")
            return False

    def is_connected(self) -> bool:
        """Check if WiFi is currently connected.

        Returns:
            bool: True if connected to WiFi, False otherwise.

        Note:
            This checks the actual connection status, not just whether
            we previously connected. WiFi can drop unexpectedly.
        """
        if self._wlan is None:
            return False
        return self._wlan.isconnected()

    def ensure_connected(self, timeout: int = 30) -> bool:
        """Ensure WiFi is connected, reconnecting if necessary.

        Call this before any network operation to handle dropped connections.
        If already connected, returns immediately. If disconnected, attempts
        to reconnect with the configured credentials.

        Args:
            timeout: Maximum seconds to wait for reconnection (default 30)

        Returns:
            bool: True if connected (was already or successfully reconnected),
                  False if reconnection failed.

        Example:
            if nm.ensure_connected():
                data = nm.http_get(url)
            else:
                # Handle offline mode
                use_cached_data()
        """
        if self.is_connected():
            return True

        print("WiFi disconnected, attempting to reconnect...")
        return self.connect_wifi(timeout=timeout)

    def _ntp_request(self, host: str) -> int | None:
        """Request time from a single NTP server using raw UDP socket.

        NTP Protocol Details:
        - Uses UDP port 123
        - Request is a 48-byte packet with first byte = 0x1B
          (0x1B = 00 011 011 in binary: LI=0, VN=3, Mode=3 for client)
        - Response is also 48 bytes
        - Transmit timestamp is at bytes 40-43 (big-endian unsigned int)

        Args:
            host: NTP server hostname (e.g., "pool.ntp.org")

        Returns:
            int: Unix timestamp (seconds since Jan 1, 1970) or None on failure.

        Note:
            Uses a 5-second socket timeout. NTP servers should respond in
            milliseconds, so 5 seconds is generous and handles slow networks.
        """
        if socket is None or struct is None:
            return None

        # Build NTP request packet (48 bytes, mostly zeros)
        # First byte: LI (2 bits) + VN (3 bits) + Mode (3 bits)
        # 0x1B = 0b00011011 = LI=0 (no warning), VN=3 (NTPv3), Mode=3 (client)
        NTP_QUERY = bytearray(48)
        NTP_QUERY[0] = 0x1B

        try:
            # Resolve hostname to IP address and get socket address tuple
            addr = socket.getaddrinfo(host, 123)[0][-1]

            # Create UDP socket (SOCK_DGRAM = UDP, vs SOCK_STREAM = TCP)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(5)  # 5 second timeout for slow networks

            # Send request and wait for response
            s.sendto(NTP_QUERY, addr)
            msg = s.recv(48)
            s.close()

            # Extract transmit timestamp from bytes 40-43
            # "!I" = network byte order (big-endian), unsigned int (4 bytes)
            ntp_timestamp = struct.unpack("!I", msg[40:44])[0]

            # Convert NTP timestamp (since 1900) to Unix timestamp (since 1970)
            unix_timestamp = ntp_timestamp - self.NTP_DELTA

            return unix_timestamp

        except Exception as e:
            print(f"NTP request to {host} failed: {e}")
            return None

    def sync_time(self) -> bool:
        """Synchronize the Pico's RTC via NTP.

        Tries each configured NTP server in sequence until one succeeds.
        On success, sets the Pico's software RTC to the received time.

        CRITICAL: The Pico W has no battery-backed RTC. After power loss,
        the RTC resets to Unix epoch (1970). This method MUST be called
        after every boot to get accurate time for schedule evaluation.

        Returns:
            bool: True if time was synced successfully, False if all servers failed.

        Note:
            After successful sync, self._time_synced is set to True.
            The RTC will maintain accurate time while the Pico is powered,
            but will reset on the next power cycle.

        Example:
            if nm.sync_time():
                print(f"Current time: {time.localtime()}")
                # Safe to evaluate schedule times now
            else:
                print("Time sync failed - staying in night light mode")
        """
        for server in self._ntp_servers:
            print(f"Trying NTP server: {server}")
            timestamp = self._ntp_request(server)

            if timestamp is not None:
                # Successfully got time from this server
                if machine is not None:
                    # Convert Unix timestamp to time tuple
                    # time.gmtime() returns: (year, month, mday, hour, minute, second, weekday, yearday)
                    tm = time.gmtime(timestamp)

                    # Set the RTC. machine.RTC().datetime() expects:
                    # (year, month, day, weekday, hour, minute, second, subsecond)
                    # Note: RTC weekday is 1-7 (Mon-Sun), gmtime weekday is 0-6 (Mon-Sun)
                    machine.RTC().datetime((
                        tm[0],      # year
                        tm[1],      # month
                        tm[2],      # day
                        tm[6] + 1,  # weekday (convert 0-6 to 1-7)
                        tm[3],      # hour
                        tm[4],      # minute
                        tm[5],      # second
                        0           # subsecond (not provided by NTP)
                    ))

                self._time_synced = True
                print(f"NTP sync successful from {server}")
                return True

        # All servers failed
        print("NTP sync failed - all servers exhausted")
        return False

    def is_time_synced(self) -> bool:
        """Check if time has been successfully synced via NTP.

        Returns:
            bool: True if sync_time() has succeeded at least once since boot.

        Note:
            This only indicates that sync was attempted successfully.
            The RTC could still drift over time (typically a few seconds per day).
        """
        return self._time_synced

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for a retry attempt.

        Exponential backoff prevents overwhelming a struggling server by
        increasing the wait time between retries. The formula is:
            delay = BASE_DELAY * (2 ^ attempt)

        With BASE_DELAY=1:
            Attempt 0: 1 * 2^0 = 1 second
            Attempt 1: 1 * 2^1 = 2 seconds
            Attempt 2: 1 * 2^2 = 4 seconds

        Args:
            attempt: Current attempt number (0-indexed, so first retry is attempt 0)

        Returns:
            float: Delay in seconds before the next retry attempt.
        """
        base_delay = config.HTTP_BASE_DELAY_S if config else self.BASE_DELAY
        return base_delay * (2 ** attempt)

    def _http_request_with_retry(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 10
    ) -> dict[str, Any] | bool | None:
        """Execute HTTP request with automatic retry and exponential backoff.

        This is the core HTTP method used by http_get() and http_post().
        It handles transient failures by retrying with increasing delays.

        Retry behavior:
        - Up to MAX_RETRIES attempts (default 3)
        - Exponential backoff between attempts (1s, 2s, 4s, ...)
        - Catches all exceptions to prevent crashes
        - Returns failure status instead of raising exceptions

        Args:
            method: HTTP method string ('GET' or 'POST')
            url: Full URL to request
            data: Request body data for POST (will be JSON-encoded)
            headers: Optional dict of HTTP headers
            timeout: Socket timeout in seconds (default 10)

        Returns:
            For GET: dict (parsed JSON response) or None on failure
            For POST: True on success, False on failure

        Note:
            This method never raises exceptions. All errors are caught,
            logged, and result in a failure return value. This is intentional
            to keep the lamp running even when network issues occur.
        """
        if requests is None:
            # Desktop testing mode - no HTTP library available
            return None if method == 'GET' else False

        # Track delays for testing purposes
        self._last_retry_delays = []

        max_retries = config.HTTP_MAX_RETRIES if config else self.MAX_RETRIES
        for attempt in range(max_retries):
            try:
                if method == 'GET':
                    response = requests.get(url, headers=headers, timeout=timeout)
                else:  # POST
                    # MicroPython's requests doesn't auto-encode JSON
                    json_data = json.dumps(data) if data else None
                    response = requests.post(url, data=json_data, headers=headers, timeout=timeout)

                if response.status_code == 200:
                    if method == 'GET':
                        result = response.json()
                        response.close()  # Important: free socket resources
                        return result
                    else:
                        response.close()
                        return True
                else:
                    # Non-200 status code - log and retry
                    print(f"HTTP {method} failed with status {response.status_code}")
                    response.close()

            except Exception as e:
                # Network error, timeout, JSON parse error, etc.
                print(f"HTTP {method} attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}")

            # Calculate and apply backoff delay (skip after last attempt)
            if attempt < max_retries - 1:
                delay = self._calculate_backoff_delay(attempt)
                self._last_retry_delays.append(delay)
                print(f"Retrying in {delay}s...")
                time.sleep(delay)

        # All retries exhausted
        print(f"HTTP {method} failed after {max_retries} attempts")
        return None if method == 'GET' else False

    def http_get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 10
    ) -> dict[str, Any] | None:
        """Perform HTTP GET request with automatic retry.

        Fetches JSON data from a URL with retry logic for transient failures.

        Args:
            url: Full URL to fetch (e.g., "https://api.example.com/schedule")
            headers: Optional dict of HTTP headers (e.g., {"Authorization": "Bearer xyz"})
            timeout: Request timeout in seconds (default 10)

        Returns:
            dict: Parsed JSON response on success
            None: On failure (after all retries exhausted)

        Example:
            headers = {"x-custom-auth": "secret_token"}
            schedule = nm.http_get("https://api.example.com/lights", headers=headers)
            if schedule:
                process_schedule(schedule)
            else:
                use_cached_schedule()
        """
        result = self._http_request_with_retry('GET', url, headers=headers, timeout=timeout)
        return result if isinstance(result, dict) else None

    def http_post(
        self,
        url: str,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
        timeout: int = 10
    ) -> bool:
        """Perform HTTP POST request with automatic retry.

        Sends JSON data to a URL with retry logic for transient failures.

        Args:
            url: Full URL to post to (e.g., "https://api.example.com/logging")
            data: Dict to send as JSON body
            headers: Optional dict of HTTP headers
            timeout: Request timeout in seconds (default 10)

        Returns:
            bool: True on success (HTTP 200), False on failure

        Example:
            log_data = {"message": "Lamp started", "level": "INFO"}
            headers = {"content-type": "application/json", "x-custom-auth": "token"}
            if nm.http_post("https://api.example.com/logging", log_data, headers):
                print("Log sent successfully")
        """
        result = self._http_request_with_retry('POST', url, data=data, headers=headers, timeout=timeout)
        return result if isinstance(result, bool) else False
