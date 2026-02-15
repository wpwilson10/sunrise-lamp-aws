# Implementation Plan: Lamp Controller Refactor

## Overview

This plan refactors the Sunrise Lamp Controller from a monolithic architecture to a modular system with proper error handling, brightness state tracking, and non-blocking execution. The implementation follows a bottom-up approach: core modules first, then integration.

## Tasks

- [x] 1. Create LED Driver module
  - [x] 1.1 Create `led_driver.py` with LEDDriver class
    - Implement `__init__` with PWM setup and brightness state initialization
    - Implement `set_brightness(warm, cool)` with internal state tracking
    - Implement `get_brightness()` returning tracked state
    - Implement `_to_duty_cycle(brightness)` with gamma correction (power 2.2)
    - Implement `night_light(brightness=0.25)` and `off()` convenience methods
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 2.7_

  - [x] 1.2 Write property test for brightness state round-trip
    - **Property 1: Brightness State Round-Trip**
    - **Validates: Requirements 2.1, 2.5**

  - [x] 1.3 Write property test for gamma correction formula
    - **Property 2: Gamma Correction Formula**
    - **Validates: Requirements 2.7**

- [x] 2. Create Network Manager module
  - [x] 2.1 Create `network_manager.py` with NetworkManager class
    - Implement `__init__` with WiFi credentials and NTP server list
    - Implement `connect_wifi(timeout=30)` with timeout handling
    - Implement `is_connected()` status check
    - _Requirements: 1.3, 3.2_

  - [x] 2.2 Implement NTP sync with multiple server fallback
    - Implement `_ntp_request(host)` using raw socket with 5s timeout
    - Implement `sync_time()` trying each server in sequence
    - Set RTC on successful sync
    - _Requirements: 1.4, 1.6, 3.4_

  - [x] 2.3 Implement HTTP methods with retry logic
    - Implement `http_get(url, headers, timeout)` with 3 retries and exponential backoff
    - Implement `http_post(url, data, headers, timeout)` with same retry logic
    - Return None/False on failure without raising exceptions
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 2.4 Write property test for retry with exponential backoff
    - **Property 9: Network Retry with Exponential Backoff**
    - **Validates: Requirements 1.1**

  - [x] 2.5 Write property test for failure after max retries
    - **Property 10: Return Failure After Max Retries**
    - **Validates: Requirements 1.2**

  - [x] 2.6 Write property test for NTP server fallback
    - **Property 11: Try All NTP Servers Before Failing**
    - **Validates: Requirements 1.4**

- [x] 3. Checkpoint - Verify LED Driver and Network Manager
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create Schedule Manager module
  - [x] 4.1 Create `schedule_manager.py` with ScheduleManager class
    - Implement `__init__` with network manager, API URL, and token
    - Implement internal state: `_cached_schedule`, `_utc_offset`, `_last_fetch_time`, `_mode`
    - _Requirements: 7.1, 9.8_

  - [x] 4.2 Implement timestamp computation
    - Implement `_compute_timestamps(entries)` converting "HH:MM" to unix timestamps
    - Apply UTC offset from server response
    - Sort entries chronologically
    - Validate brightness values (0-100 range)
    - _Requirements: 7.2, 7.4, 7.6, 8.2_

  - [x] 4.3 Implement schedule fetching and caching
    - Implement `fetch_schedule()` using network manager
    - Parse server response and call `_compute_timestamps`
    - Handle missing/invalid data gracefully
    - _Requirements: 7.1, 7.3, 8.5_

  - [x] 4.4 Implement refresh logic
    - Implement `needs_refresh()` checking: no schedule, past last entry, or interval elapsed
    - Implement `get_entries()`, `get_mode()`, `has_valid_schedule()` accessors
    - _Requirements: 9.5_

  - [x] 4.5 Write property test for schedule entries sorted
    - **Property 6: Schedule Entries Sorted Chronologically**
    - **Validates: Requirements 4.5, 7.4**

  - [x] 4.6 Write property test for timestamp computation
    - **Property 7: Timestamp Computation with Timezone**
    - **Validates: Requirements 7.2, 8.2**

  - [x] 4.7 Write property test for brightness validation
    - **Property 8: Brightness Validation Range**
    - **Validates: Requirements 7.6**

  - [x] 4.8 Write property test for refresh conditions
    - **Property 12: Schedule Refresh Conditions**
    - **Validates: Requirements 9.5**

- [x] 5. Create Transition Engine module
  - [x] 5.1 Create `transition_engine.py` with TransitionEngine class
    - Implement `__init__` with schedule manager and LED driver references
    - Implement `update()` calling `get_current_target()` and setting LEDs
    - _Requirements: 2.3, 9.2_

  - [x] 5.2 Implement brightness interpolation
    - Implement `get_current_target()` with linear interpolation
    - Find surrounding schedule entries based on current time
    - Handle edge cases: before first entry, after last entry
    - Return night light fallback if no schedule
    - _Requirements: 2.6, 4.1, 4.2, 4.3, 4.4_

  - [x] 5.3 Write property test for linear interpolation
    - **Property 3: Linear Interpolation Correctness**
    - **Validates: Requirements 2.6**

  - [x] 5.4 Write property test for brightness at entry time
    - **Property 4: Brightness Equals Entry at Entry Time**
    - **Validates: Requirements 4.1**

  - [x] 5.5 Write property test for past entry handling
    - **Property 5: Skip to Most Recent Past Entry**
    - **Validates: Requirements 4.4**

- [x] 6. Checkpoint - Verify Schedule Manager and Transition Engine
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Create Lamp Controller and integrate modules
  - [x] 7.1 Update `config.py` with new configuration options
    - Add `NTP_SERVERS` list
    - Add `UPDATE_INTERVAL_MS` (default 5000)
    - Add `SCHEDULE_REFRESH_HOURS` (default 6)
    - Rename API config keys for consistency
    - _Requirements: 1.6, 9.1_

  - [x] 7.2 Create LampController class in `main.py`
    - Implement `__init__` initializing all module instances
    - Implement `_startup_sequence()` with night light → WiFi → NTP → schedule flow
    - Log each startup phase
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 7.3 Implement timer-based execution
    - Implement `start()` setting up periodic timer
    - Implement `_on_timer(timer)` callback checking refresh and updating brightness
    - Add exception handling with night light fallback
    - _Requirements: 5.3, 9.1, 9.2, 9.3, 9.4_

  - [x] 7.4 Write unit tests for startup sequence
    - Test night light set before network operations
    - Test fallback behavior on WiFi/NTP/schedule failures
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 8. Update server API contract (documentation)
  - [x] 8.1 Document new server response format
    - Create `api_contract.md` documenting expected JSON structure
    - Include `mode`, `utc_offset`, `entries` array format
    - Document optional `server_time` field
    - _Requirements: 7.1, 8.1_

- [x] 9. Final checkpoint - Full integration test
  - All 17 tests pass
  - Verify startup sequence works on actual hardware (requires manual testing)
  - Verify smooth transitions over time (requires manual testing)
  - Verify schedule refresh works correctly (requires manual testing)

# WPW

- Are we logging to AWS?
- Are env variables used?
- Does wifi check to be reconnected reguarly?
- type hints?

## Notes

- All tasks are required for comprehensive implementation
- Property tests should run on desktop Python with pytest/hypothesis
- Hardware testing requires manual verification on Pi Pico W
- The server API changes (Requirement 8.1) are documented but not implemented here
