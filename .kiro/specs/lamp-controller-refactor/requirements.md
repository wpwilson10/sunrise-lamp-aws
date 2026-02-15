# Requirements Document

## Introduction

This specification defines the requirements for refactoring the Sunrise Lamp Controller to improve stability, error handling, and transition accuracy. The current implementation suffers from network timeout errors, incorrect brightness state tracking causing sudden jumps, and unreliable startup behavior.

## Platform Constraints

This system runs on Raspberry Pi Pico W using MicroPython. Key constraints:

- **No battery-backed RTC**: Time resets to epoch on power loss; NTP sync required for accurate time
- **Limited memory**: ~264KB RAM; avoid large data structures and minimize object allocation
- **Available modules**: `machine` (PWM, Timer, Pin, RTC), `network` (WLAN), `ntptime`, `requests`, `time`, `json`, `socket`
- **PWM**: 16-bit resolution (0-65535), 8 slices with 2 channels each, frequency range 8Hz-62.5MHz
- **Timers**: Software timers only (no hardware timer IDs), callbacks can be soft or hard IRQ
- **Network**: Single WLAN interface, blocking socket operations by default

## Glossary

- **Lamp_Controller**: The main system managing LED brightness transitions and schedule execution
- **LED_Driver**: Component responsible for PWM control of warm and cool LED channels
- **Schedule_Manager**: Component that fetches, validates, and manages lighting schedules
- **Network_Manager**: Component handling WiFi connectivity and network operations
- **Brightness_State**: The current tracked brightness levels for warm and cool LEDs (0.0-1.0)
- **Transition_Engine**: Component that calculates and executes smooth brightness changes
- **Gamma_Correction**: Mathematical adjustment (power of 2.2) converting perceived brightness to PWM duty cycle

## Requirements

### Requirement 1: Reliable Network Operations

**User Story:** As a device owner, I want the lamp to handle network failures gracefully, so that temporary connectivity issues don't cause errors or incorrect behavior.

#### Acceptance Criteria

1. WHEN a network operation times out, THE Network_Manager SHALL retry the operation up to 3 times with exponential backoff
2. WHEN all retry attempts fail, THE Network_Manager SHALL log the failure and return a failure status without crashing
3. WHEN WiFi connection is lost during operation, THE Lamp_Controller SHALL continue operating with the last known schedule
4. WHEN NTP time sync fails with the primary server, THE Network_Manager SHALL attempt sync with configured backup NTP servers before reporting failure
5. IF the schedule API is unreachable, THEN THE Schedule_Manager SHALL use a cached schedule if available or fall back to night light mode
6. THE Network_Manager SHALL support a configurable list of NTP servers to try in sequence (default: pool.ntp.org, time.google.com, time.cloudflare.com)

### Requirement 2: Accurate Brightness State Tracking

**User Story:** As a user, I want smooth lighting transitions without sudden brightness jumps, so that the lamp provides a natural lighting experience.

#### Acceptance Criteria

1. THE LED_Driver SHALL maintain an internal Brightness_State that tracks the current perceived brightness (0.0-1.0) for each channel
2. WHEN setting LED brightness, THE LED_Driver SHALL update the internal Brightness_State before applying PWM changes
3. WHEN starting a transition, THE Transition_Engine SHALL read the current brightness from the LED_Driver's internal state, not from PWM duty cycle
4. WHEN the system starts, THE LED_Driver SHALL initialize Brightness_State to match the initial PWM values set
5. THE LED_Driver SHALL provide a method to get current brightness that returns the tracked Brightness_State
6. THE Transition_Engine SHALL perform linear interpolation on perceived brightness values to ensure equal perceptual steps
7. THE LED_Driver SHALL apply gamma correction (power of 2.2) only when converting perceived brightness to PWM duty cycle
8. THE LED_Driver SHALL NOT attempt to reverse-calculate perceived brightness from PWM duty cycle values

### Requirement 3: Robust Startup Sequence

**User Story:** As a device owner, I want the lamp to start reliably even when network services are unavailable, so that the lamp always provides some lighting.

#### Acceptance Criteria

1. WHEN the device powers on, THE Lamp_Controller SHALL immediately set LEDs to night light mode before attempting network operations
2. WHEN WiFi connection fails after 30 seconds, THE Lamp_Controller SHALL continue in night light mode and retry connection periodically
3. WHEN schedule fetch fails on startup, THE Lamp_Controller SHALL operate in night light mode until a schedule is successfully retrieved
4. WHEN NTP sync fails on startup, THE Lamp_Controller SHALL remain in night light mode since schedule times cannot be evaluated without accurate time
5. THE Lamp_Controller SHALL log each startup phase completion for debugging
6. WHEN NTP sync succeeds after initial failure, THE Lamp_Controller SHALL immediately attempt to fetch and apply the schedule

### Requirement 4: Schedule Transition Timing

**User Story:** As a user, I want transitions to start at the correct times and reach target brightness exactly when scheduled, so that lighting matches natural daylight patterns.

#### Acceptance Criteria

1. WHEN a schedule entry time arrives, THE Transition_Engine SHALL have already completed the transition to that entry's target brightness
2. WHEN calculating transition duration, THE Schedule_Manager SHALL compute the time between the previous entry and the current entry
3. WHEN no previous entry exists, THE Transition_Engine SHALL use a minimum transition duration of 60 seconds
4. WHEN multiple schedule entries are in the past, THE Lamp_Controller SHALL skip to the most recent past entry's brightness immediately, then transition to the next future entry
5. THE Schedule_Manager SHALL validate that schedule entries are in chronological order

### Requirement 5: Error Recovery and Logging

**User Story:** As a developer, I want comprehensive error logging and automatic recovery, so that I can diagnose issues and the lamp self-heals from transient failures.

#### Acceptance Criteria

1. WHEN any operation fails, THE Lamp_Controller SHALL log the error with context (operation name, error type, relevant parameters)
2. WHEN logging fails due to network issues, THE Lamp_Controller SHALL buffer log messages and retry on next successful connection
3. IF an unhandled exception occurs in the main loop, THEN THE Lamp_Controller SHALL log the error, reset to night light mode, and continue operation
4. WHEN the device has been running for 24 hours without a successful schedule update, THE Lamp_Controller SHALL log a warning
5. THE Lamp_Controller SHALL log successful operations at DEBUG level and failures at ERROR level

### Requirement 6: Modular Architecture

**User Story:** As a developer, I want the code organized into separate modules with clear responsibilities, so that I can test and maintain components independently.

#### Acceptance Criteria

1. THE Lamp_Controller SHALL separate concerns into distinct modules: LED_Driver, Network_Manager, Schedule_Manager, and Transition_Engine
2. WHEN modules communicate, they SHALL use defined interfaces rather than global state
3. THE LED_Driver SHALL encapsulate all PWM and brightness operations
4. THE Network_Manager SHALL encapsulate all WiFi and HTTP operations
5. THE Schedule_Manager SHALL encapsulate schedule fetching, caching, and validation
6. THE Transition_Engine SHALL encapsulate brightness interpolation and timing calculations

### Requirement 7: Simplified Schedule Data Model

**User Story:** As a developer, I want a minimal data contract with the server, so that the Pico can operate with less server dependency and handle schedule interpretation locally.

#### Acceptance Criteria

1. THE Schedule_Manager SHALL accept schedule data containing: mode, timezone offset, and a list of schedule entries with time (HH:MM format), warm brightness (0-100), and cool brightness (0-100)
2. THE Schedule_Manager SHALL compute unix timestamps locally from time strings using the Pico's synced RTC and the provided timezone offset
3. WHEN in dayNight mode, THE server SHALL provide sun event times (civil_twilight_begin, sunrise, sunset, civil_twilight_end) as schedule entries
4. THE Schedule_Manager SHALL sort schedule entries chronologically after timestamp computation
5. THE server MAY provide a current UTC timestamp as a backup time source
6. THE Schedule_Manager SHALL validate that brightness values are within 0-100 range
7. THE Transition_Engine SHALL accept a sequence of (target_time, warm_brightness, cool_brightness) tuples and compute transitions between them

### Requirement 8: Timezone and Locality Handling

**User Story:** As a user, I want the lamp to correctly interpret schedule times in my local timezone, so that sunrise simulation happens at the right time regardless of daylight saving changes.

#### Acceptance Criteria

1. THE server SHALL provide the current UTC offset in seconds (e.g., -18000 for EST, -14400 for EDT) with each schedule response
2. THE Schedule_Manager SHALL apply the timezone offset when converting local time strings to unix timestamps
3. WHEN the timezone offset changes (e.g., DST transition), THE Schedule_Manager SHALL use the new offset from the next schedule fetch
4. THE Schedule_Manager SHALL store the current timezone offset and use it until a new schedule is fetched
5. IF no timezone offset is provided, THEN THE Schedule_Manager SHALL default to UTC (offset 0) and log a warning

### Requirement 9: Non-Blocking Schedule Execution

**User Story:** As a user, I want the lamp to respond to schedule updates promptly and have smooth transitions, so that mode changes take effect quickly and brightness changes are imperceptible.

#### Acceptance Criteria

1. THE Lamp_Controller SHALL use a periodic timer to update LED brightness with configurable interval (default 5 seconds for smooth transitions)
2. WHEN the timer fires, THE Transition_Engine SHALL calculate the current target brightness based on time position between cached schedule entries and apply it immediately
3. THE Lamp_Controller SHALL NOT use blocking sleep calls longer than the timer interval
4. WHEN a new schedule is fetched, THE Transition_Engine SHALL immediately recalculate brightness targets using the new schedule
5. THE Schedule_Manager SHALL fetch a new schedule from the server only when: (a) no schedule exists, (b) current time exceeds the last schedule entry by more than 1 hour, or (c) a configurable refresh interval has elapsed (default 6 hours)
6. WHEN schedule fetch fails, THE Lamp_Controller SHALL continue using the cached schedule and retry on the next refresh interval
7. FOR a 30-minute transition, THE Transition_Engine SHALL produce at least 360 brightness updates (one per 5 seconds) ensuring imperceptible step changes
8. THE Schedule_Manager SHALL cache the current schedule in memory and use it for all brightness calculations between server fetches
