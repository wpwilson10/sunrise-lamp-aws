"""Tests for Schedule Manager module.

Tests the unified brightnessSchedule format processing, clock drift detection,
and schedule fetching functionality.
"""

from hypothesis import given, settings, strategies as st
from unittest.mock import Mock, patch
import time

from schedule_manager import ScheduleManager


def create_mock_network(response=None):
    """Create a mock NetworkManager with specified response.

    Args:
        response: Dict to return from http_get, or None for failure

    Returns:
        Mock NetworkManager instance
    """
    mock = Mock()
    mock.http_get.return_value = response
    return mock


class TestProcessBrightnessSchedule:
    """Tests for _process_brightness_schedule method."""

    def test_valid_entries_are_processed(self):
        """Valid entries are converted to internal format."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": 1000, "warmBrightness": 50, "coolBrightness": 30, "label": "test1"},
            {"unixTime": 2000, "warmBrightness": 100, "coolBrightness": 0, "label": "test2"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert len(result) == 2
        assert result[0] == {"unix_time": 1000, "warm": 0.5, "cool": 0.3, "label": "test1"}
        assert result[1] == {"unix_time": 2000, "warm": 1.0, "cool": 0.0, "label": "test2"}

    def test_brightness_normalized_to_float(self):
        """Brightness values are normalized from 0-100 to 0.0-1.0."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": 1000, "warmBrightness": 0, "coolBrightness": 100, "label": "test"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert result[0]["warm"] == 0.0
        assert result[0]["cool"] == 1.0

    def test_missing_unix_time_skipped(self):
        """Entries without unixTime are skipped."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"warmBrightness": 50, "coolBrightness": 30, "label": "missing_time"},
            {"unixTime": 1000, "warmBrightness": 50, "coolBrightness": 30, "label": "valid"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert len(result) == 1
        assert result[0]["label"] == "valid"

    def test_missing_brightness_skipped(self):
        """Entries without brightness values are skipped."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": 1000, "coolBrightness": 30, "label": "missing_warm"},
            {"unixTime": 2000, "warmBrightness": 50, "label": "missing_cool"},
            {"unixTime": 3000, "warmBrightness": 50, "coolBrightness": 30, "label": "valid"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert len(result) == 1
        assert result[0]["label"] == "valid"

    def test_invalid_brightness_skipped(self):
        """Entries with brightness values outside 0-100 are skipped."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": 1000, "warmBrightness": -10, "coolBrightness": 30, "label": "negative"},
            {"unixTime": 2000, "warmBrightness": 50, "coolBrightness": 150, "label": "over_100"},
            {"unixTime": 3000, "warmBrightness": 50, "coolBrightness": 30, "label": "valid"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert len(result) == 1
        assert result[0]["label"] == "valid"

    def test_entries_sorted_by_unix_time(self):
        """Entries are sorted chronologically by unix_time."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": 3000, "warmBrightness": 30, "coolBrightness": 30, "label": "third"},
            {"unixTime": 1000, "warmBrightness": 10, "coolBrightness": 10, "label": "first"},
            {"unixTime": 2000, "warmBrightness": 20, "coolBrightness": 20, "label": "second"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert result[0]["label"] == "first"
        assert result[1]["label"] == "second"
        assert result[2]["label"] == "third"

    def test_missing_label_defaults_to_empty_string(self):
        """Entries without label get empty string as default."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": 1000, "warmBrightness": 50, "coolBrightness": 30},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert result[0]["label"] == ""

    @settings(max_examples=100)
    @given(
        unix_time=st.integers(min_value=0, max_value=2000000000),
        warm=st.integers(min_value=0, max_value=100),
        cool=st.integers(min_value=0, max_value=100)
    )
    def test_property_brightness_normalization(self, unix_time, warm, cool):
        """Property: Brightness values are correctly normalized to 0.0-1.0."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        schedule = [
            {"unixTime": unix_time, "warmBrightness": warm, "coolBrightness": cool, "label": "test"},
        ]

        result = manager._process_brightness_schedule(schedule)

        assert len(result) == 1
        assert abs(result[0]["warm"] - warm / 100.0) < 0.0001
        assert abs(result[0]["cool"] - cool / 100.0) < 0.0001


class TestCheckClockDrift:
    """Tests for _check_clock_drift method."""

    def test_no_warning_within_threshold(self, capsys):
        """No warning when drift is within 5 minute threshold."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        current_time = int(time.time())
        server_time = current_time + 60  # 1 minute drift

        manager._check_clock_drift(server_time)

        captured = capsys.readouterr()
        assert "Warning" not in captured.out

    def test_warning_when_drift_exceeds_threshold(self, capsys):
        """Warning logged when drift exceeds 5 minute threshold."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        current_time = int(time.time())
        server_time = current_time + 400  # ~6.7 minutes drift

        manager._check_clock_drift(server_time)

        captured = capsys.readouterr()
        assert "Warning: Clock drift detected" in captured.out
        assert "Drift=400s" in captured.out

    def test_warning_for_negative_drift(self, capsys):
        """Warning logged for negative drift (server behind local)."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        current_time = int(time.time())
        server_time = current_time - 400  # Server 6.7 minutes behind

        manager._check_clock_drift(server_time)

        captured = capsys.readouterr()
        assert "Warning: Clock drift detected" in captured.out

    def test_exactly_at_threshold_no_warning(self, capsys):
        """No warning when drift is exactly at threshold (300s)."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        current_time = int(time.time())
        server_time = current_time + 300  # Exactly 5 minutes

        manager._check_clock_drift(server_time)

        captured = capsys.readouterr()
        assert "Warning" not in captured.out


class TestFetchSchedule:
    """Tests for fetch_schedule method with unified format."""

    def test_successful_fetch_with_unified_format(self):
        """Successfully fetches and processes unified format response."""
        response = {
            "mode": "dayNight",
            "serverTime": int(time.time()),
            "brightnessSchedule": [
                {"time": "06:30", "unixTime": 1000, "warmBrightness": 20, "coolBrightness": 0, "label": "dawn"},
                {"time": "07:00", "unixTime": 2000, "warmBrightness": 75, "coolBrightness": 100, "label": "sunrise"},
            ]
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")

        result = manager.fetch_schedule()

        assert result is True
        assert manager.get_mode() == "dayNight"
        entries = manager.get_entries()
        assert len(entries) == 2
        assert entries[0]["warm"] == 0.2
        assert entries[1]["cool"] == 1.0

    def test_empty_brightness_schedule_returns_false(self):
        """Returns False when brightnessSchedule is empty."""
        response = {
            "mode": "dayNight",
            "serverTime": int(time.time()),
            "brightnessSchedule": []
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")

        result = manager.fetch_schedule()

        assert result is False

    def test_missing_brightness_schedule_returns_false(self):
        """Returns False when brightnessSchedule is missing."""
        response = {
            "mode": "dayNight",
            "serverTime": int(time.time()),
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")

        result = manager.fetch_schedule()

        assert result is False

    def test_network_failure_returns_false(self):
        """Returns False when network request fails."""
        network = create_mock_network(None)
        manager = ScheduleManager(network, "http://test", "token")

        result = manager.fetch_schedule()

        assert result is False

    def test_clock_drift_check_called_with_server_time(self, capsys):
        """Clock drift check is performed when serverTime is present."""
        # Server time 10 minutes in future - should trigger warning
        server_time = int(time.time()) + 600
        response = {
            "mode": "dayNight",
            "serverTime": server_time,
            "brightnessSchedule": [
                {"unixTime": 1000, "warmBrightness": 50, "coolBrightness": 50, "label": "test"},
            ]
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")

        manager.fetch_schedule()

        captured = capsys.readouterr()
        assert "Warning: Clock drift detected" in captured.out

    def test_demo_mode_uses_config_schedule(self):
        """Demo mode uses hardcoded config schedule, not server entries."""
        response = {"mode": "demo"}
        network = create_mock_network(response)

        with patch('schedule_manager.config') as mock_config:
            mock_config.DEFAULT_SCHEDULE_MODE = "dayNight"
            mock_config.DEMO_SCHEDULE = [
                (0, 10, 0, "night"),
                (5, 50, 50, "day"),
            ]
            mock_config.DEMO_CYCLE_DURATION_S = 15

            manager = ScheduleManager(network, "http://test", "token")
            result = manager.fetch_schedule()

            assert result is True
            assert manager.is_demo_mode() is True
            entries = manager.get_entries()
            assert len(entries) == 2

    def test_last_fetch_time_updated(self):
        """last_fetch_time is updated on successful fetch."""
        response = {
            "mode": "dayNight",
            "serverTime": int(time.time()),
            "brightnessSchedule": [
                {"unixTime": 1000, "warmBrightness": 50, "coolBrightness": 50, "label": "test"},
            ]
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")

        before = int(time.time())
        manager.fetch_schedule()
        after = int(time.time())

        assert before <= manager.get_last_fetch_time() <= after


class TestNeedsRefresh:
    """Tests for needs_refresh method."""

    def test_needs_refresh_when_no_schedule(self):
        """Returns True when no schedule is cached."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        assert manager.needs_refresh() is True

    def test_no_refresh_needed_with_valid_schedule(self):
        """Returns False when schedule is valid and fresh."""
        response = {
            "mode": "dayNight",
            "serverTime": int(time.time()),
            "brightnessSchedule": [
                {"unixTime": int(time.time()) + 7200, "warmBrightness": 50, "coolBrightness": 50, "label": "future"},
            ]
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")
        manager.fetch_schedule()

        assert manager.needs_refresh() is False


class TestHasValidSchedule:
    """Tests for has_valid_schedule method."""

    def test_false_when_no_schedule(self):
        """Returns False when no schedule is cached."""
        network = create_mock_network()
        manager = ScheduleManager(network, "http://test", "token")

        assert manager.has_valid_schedule() is False

    def test_true_after_successful_fetch(self):
        """Returns True after successful fetch."""
        response = {
            "mode": "dayNight",
            "serverTime": int(time.time()),
            "brightnessSchedule": [
                {"unixTime": 1000, "warmBrightness": 50, "coolBrightness": 50, "label": "test"},
            ]
        }
        network = create_mock_network(response)
        manager = ScheduleManager(network, "http://test", "token")
        manager.fetch_schedule()

        assert manager.has_valid_schedule() is True
