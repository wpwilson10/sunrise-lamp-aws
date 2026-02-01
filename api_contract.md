# Schedule API Contract

This document defines the expected JSON structure for communication between the Sunrise Lamp Controller (Pico W client) and the schedule server.

## Endpoint

```
GET /lights
```

### Request Headers

| Header | Value | Description |
|--------|-------|-------------|
| `x-custom-auth` | `<api_token>` | Authentication token for the API |

### Response Format

```json
{
  "mode": "dayNight",
  "utc_offset": -18000,
  "server_time": 1703894400,
  "entries": [
    {
      "time": "06:30",
      "warm": 20,
      "cool": 0,
      "label": "civil_twilight_begin"
    },
    {
      "time": "07:00",
      "warm": 80,
      "cool": 30,
      "label": "sunrise"
    }
  ]
}
```

## Field Definitions

### Root Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | string | Yes | Schedule mode: `"dayNight"`, `"scheduled"`, or `"demo"` |
| `utc_offset` | integer | Yes | UTC offset in seconds (negative for west of UTC, e.g., -18000 for EST) |
| `server_time` | integer | No | Current server time as Unix timestamp (backup time source) |
| `entries` | array | Yes | Array of schedule entry objects (also accepts key `"schedule"`) |

### Schedule Entry Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `time` | string | Yes | Local time in "HH:MM" format (24-hour) |
| `warm` | integer | Yes | Warm LED brightness 0-100 (also accepts `warmBrightness`) |
| `cool` | integer | Yes | Cool LED brightness 0-100 (also accepts `coolBrightness`) |
| `label` | string | No | Human-readable label for the entry (e.g., "sunrise", "bedtime") |

## Modes

### dayNight Mode

For sun-based schedules. Server provides sun event times as entries:

```json
{
  "mode": "dayNight",
  "utc_offset": -18000,
  "entries": [
    { "time": "06:30", "warm": 20, "cool": 0, "label": "civil_twilight_begin" },
    { "time": "07:00", "warm": 80, "cool": 30, "label": "sunrise" },
    { "time": "17:30", "warm": 80, "cool": 30, "label": "sunset" },
    { "time": "18:00", "warm": 40, "cool": 0, "label": "civil_twilight_end" },
    { "time": "21:00", "warm": 25, "cool": 0, "label": "bedtime" },
    { "time": "22:00", "warm": 10, "cool": 0, "label": "night" }
  ]
}
```

### scheduled Mode

For custom user-defined schedules:

```json
{
  "mode": "scheduled",
  "utc_offset": -18000,
  "entries": [
    { "time": "06:00", "warm": 50, "cool": 50, "label": "morning" },
    { "time": "22:00", "warm": 20, "cool": 0, "label": "evening" }
  ]
}
```

### demo Mode

For demonstration/testing with rapid transitions. When the server returns `mode: "demo"`, the client uses a **hardcoded local demo schedule** instead of the server-provided entries. This allows the lamp to demonstrate its capabilities with a 15-second looping day/night cycle.

**Server response for demo mode:**

```json
{
  "mode": "demo"
}
```

**Note:** The `utc_offset` and `entries` fields are ignored when mode is `"demo"`. The client uses its built-in demo schedule configured in `config.py`:

| Time (seconds) | Warm | Cool | Phase |
|----------------|------|------|-------|
| 0 | 10% | 0% | Night |
| 2 | 25% | 0% | Pre-dawn |
| 4 | 60% | 20% | Dawn |
| 6 | 100% | 80% | Sunrise |
| 8 | 90% | 100% | Midday |
| 10 | 80% | 50% | Afternoon |
| 12 | 50% | 10% | Sunset |
| 14 | 20% | 0% | Dusk |
| 15 | 10% | 0% | Night (loop) |

The demo cycle is configurable via `DEMO_CYCLE_DURATION_S` and `DEMO_SCHEDULE` in `config.py`.

## Timezone Handling

The `utc_offset` field specifies the offset from UTC in seconds:

| Timezone | utc_offset | Example |
|----------|------------|---------|
| EST (UTC-5) | -18000 | New York in winter |
| EDT (UTC-4) | -14400 | New York in summer |
| PST (UTC-8) | -28800 | Los Angeles in winter |
| UTC | 0 | Server default |

The Pico's RTC is set to UTC via NTP. The client converts local time strings to UTC timestamps using:

```
unix_time = local_timestamp - utc_offset
```

## Validation Rules

1. **Time format**: Must be "HH:MM" with valid values (00-23 for hours, 00-59 for minutes)
2. **Brightness range**: Values must be 0-100 (inclusive)
3. **Entry order**: Entries should be in chronological order (client will sort if needed)
4. **Non-empty**: At least one entry must be provided

## Error Handling

If the response cannot be parsed or validated:

1. Client logs the error
2. Client uses cached schedule if available
3. Client falls back to night light mode if no cache

## Client Behavior

### Schedule Refresh

The client fetches a new schedule when:

1. No schedule exists (first boot)
2. Current time exceeds last entry by more than 1 hour
3. Refresh interval elapsed (default: 6 hours)

### Brightness Interpolation

Between schedule entries, the client performs linear interpolation:

```
progress = (current_time - prev_entry.time) / (next_entry.time - prev_entry.time)
brightness = prev_entry.brightness + (next_entry.brightness - prev_entry.brightness) * progress
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Before first entry | Use first entry's brightness |
| After last entry | Use last entry's brightness |
| No schedule | Night light mode (warm=25%, cool=0%) |
| Missing `utc_offset` | Default to UTC (0), log warning |
