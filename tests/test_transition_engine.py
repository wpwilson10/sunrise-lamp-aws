"""Property-based tests for Transition Engine module.

Uses hypothesis for property-based testing with minimum 100 iterations per property.
Tests linear interpolation, brightness at entry times, and past entry handling.
"""

from hypothesis import given, settings, strategies as st
from unittest.mock import Mock
import time

from transition_engine import TransitionEngine
from led_driver import LEDDriver


def create_mock_schedule_manager(entries=None, has_valid=True, is_demo=False):
    """Create a mock ScheduleManager with specified entries.

    Args:
        entries: List of schedule entry dicts, or None for empty schedule
        has_valid: Whether has_valid_schedule() returns True
        is_demo: Whether is_demo_mode() returns True

    Returns:
        Mock ScheduleManager instance
    """
    mock = Mock()
    mock.get_entries.return_value = entries if entries else []
    mock.has_valid_schedule.return_value = has_valid and entries is not None and len(entries) > 0
    mock.is_demo_mode.return_value = is_demo
    mock.get_demo_cycle_duration.return_value = 15
    return mock


class TestTransitionEngineProperties:
    """Property-based tests for TransitionEngine class."""

    @settings(max_examples=100)
    @given(
        start_warm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        start_cool=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        end_warm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        end_cool=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        progress=st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    )
    def test_linear_interpolation_correctness(self, start_warm, start_cool, end_warm, end_cool, progress):
        """Property 3: Linear Interpolation Correctness
        
        For any start brightness, end brightness, and progress value in [0.0, 1.0],
        the interpolated brightness should equal start + (end - start) * progress.
        
        Feature: lamp-controller-refactor, Property 3: Linear Interpolation Correctness
        Validates: Requirements 2.6
        """
        # Create schedule with two entries
        base_time = int(time.time())
        duration = 3600  # 1 hour between entries
        
        entries = [
            {"unix_time": base_time, "warm": start_warm, "cool": start_cool, "label": "start"},
            {"unix_time": base_time + duration, "warm": end_warm, "cool": end_cool, "label": "end"}
        ]
        
        mock_schedule = create_mock_schedule_manager(entries)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        # Calculate the time that corresponds to the given progress
        current_time = base_time + (duration * progress)
        
        # Mock time.time() to return our calculated time
        import transition_engine
        original_time = transition_engine.time.time
        transition_engine.time.time = lambda: current_time
        
        try:
            warm, cool = engine.get_current_target()
            
            # Calculate expected values using linear interpolation formula
            expected_warm = start_warm + (end_warm - start_warm) * progress
            expected_cool = start_cool + (end_cool - start_cool) * progress
            
            # Allow small floating point tolerance
            assert abs(warm - expected_warm) < 0.0001, f"Warm: {warm} != {expected_warm}"
            assert abs(cool - expected_cool) < 0.0001, f"Cool: {cool} != {expected_cool}"
        finally:
            transition_engine.time.time = original_time


    @settings(max_examples=100)
    @given(
        warm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        cool=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        entry_index=st.integers(min_value=0, max_value=3)  # 0-3 to leave room for next entry
    )
    def test_brightness_equals_entry_at_entry_time(self, warm, cool, entry_index):
        """Property 4: Brightness Equals Entry at Entry Time
        
        For any schedule with entries and any time T exactly equal to an entry's
        unix_time, the calculated target brightness should equal that entry's
        brightness values exactly.
        
        Feature: lamp-controller-refactor, Property 4: Brightness Equals Entry at Entry Time
        Validates: Requirements 4.1
        """
        # Create schedule with multiple entries
        base_time = int(time.time())
        num_entries = 5
        
        entries = []
        for i in range(num_entries):
            # Use different brightness for each entry, but the target entry uses our test values
            if i == entry_index:
                entries.append({
                    "unix_time": base_time + (i * 3600),
                    "warm": warm,
                    "cool": cool,
                    "label": f"entry_{i}"
                })
            else:
                # Other entries have different values
                entries.append({
                    "unix_time": base_time + (i * 3600),
                    "warm": (i * 0.2) % 1.0,
                    "cool": ((i + 1) * 0.15) % 1.0,
                    "label": f"entry_{i}"
                })
        
        mock_schedule = create_mock_schedule_manager(entries)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        # Set time exactly at the target entry
        target_time = entries[entry_index]["unix_time"]
        
        import transition_engine
        original_time = transition_engine.time.time
        transition_engine.time.time = lambda: float(target_time)
        
        try:
            result_warm, result_cool = engine.get_current_target()
            
            # At exactly entry time T:
            # - The loop finds the first entry where unix_time > T
            # - prev_entry is set to the entry at T (our target entry)
            # - elapsed = T - T = 0, so progress = 0
            # - Result = prev_entry's brightness = our target entry's brightness
            #
            # Exception: If entry_index is the last entry (4), we're past all entries
            # and return the last entry's brightness directly.
            # We limit entry_index to 0-3 to ensure there's always a next entry.
            
            assert abs(result_warm - warm) < 0.0001, f"Warm: {result_warm} != {warm}"
            assert abs(result_cool - cool) < 0.0001, f"Cool: {result_cool} != {cool}"
        finally:
            transition_engine.time.time = original_time

    @settings(max_examples=100)
    @given(
        num_past_entries=st.integers(min_value=2, max_value=5),
        time_offset=st.floats(min_value=0.1, max_value=0.9, allow_nan=False)
    )
    def test_skip_to_most_recent_past_entry(self, num_past_entries, time_offset):
        """Property 5: Skip to Most Recent Past Entry
        
        For any schedule and any time T that is past multiple entries but before
        the next entry, the starting brightness for interpolation should be the
        most recent past entry's brightness.
        
        Feature: lamp-controller-refactor, Property 5: Skip to Most Recent Past Entry
        Validates: Requirements 4.4
        """
        base_time = int(time.time())
        
        # Create entries: some in the past, one in the future
        entries = []
        for i in range(num_past_entries):
            entries.append({
                "unix_time": base_time - ((num_past_entries - i) * 3600),  # Past entries
                "warm": i * 0.2,
                "cool": i * 0.15,
                "label": f"past_{i}"
            })
        
        # Add one future entry
        future_entry = {
            "unix_time": base_time + 3600,  # 1 hour in future
            "warm": 0.9,
            "cool": 0.8,
            "label": "future"
        }
        entries.append(future_entry)
        
        mock_schedule = create_mock_schedule_manager(entries)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        # Set current time between last past entry and future entry
        most_recent_past = entries[num_past_entries - 1]
        duration = future_entry["unix_time"] - most_recent_past["unix_time"]
        current_time = most_recent_past["unix_time"] + (duration * time_offset)
        
        import transition_engine
        original_time = transition_engine.time.time
        transition_engine.time.time = lambda: current_time
        
        try:
            warm, cool = engine.get_current_target()
            
            # Brightness should be interpolated between most recent past and future
            # It should be between the two values (or equal if they're the same)
            prev_warm = most_recent_past["warm"]
            next_warm = future_entry["warm"]
            prev_cool = most_recent_past["cool"]
            next_cool = future_entry["cool"]
            
            # Check warm is between prev and next (inclusive)
            min_warm = min(prev_warm, next_warm)
            max_warm = max(prev_warm, next_warm)
            assert min_warm - 0.0001 <= warm <= max_warm + 0.0001, \
                f"Warm {warm} not between {min_warm} and {max_warm}"
            
            # Check cool is between prev and next (inclusive)
            min_cool = min(prev_cool, next_cool)
            max_cool = max(prev_cool, next_cool)
            assert min_cool - 0.0001 <= cool <= max_cool + 0.0001, \
                f"Cool {cool} not between {min_cool} and {max_cool}"
        finally:
            transition_engine.time.time = original_time


class TestTransitionEngineEdgeCases:
    """Unit tests for edge cases in TransitionEngine."""

    def test_no_schedule_returns_night_light(self):
        """When no schedule exists, return night light fallback."""
        mock_schedule = create_mock_schedule_manager(entries=None)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        warm, cool = engine.get_current_target()
        
        assert warm == TransitionEngine.NIGHT_LIGHT_WARM
        assert cool == TransitionEngine.NIGHT_LIGHT_COOL

    def test_empty_schedule_returns_night_light(self):
        """When schedule is empty, return night light fallback."""
        mock_schedule = create_mock_schedule_manager(entries=[])
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        warm, cool = engine.get_current_target()
        
        assert warm == TransitionEngine.NIGHT_LIGHT_WARM
        assert cool == TransitionEngine.NIGHT_LIGHT_COOL

    def test_past_all_entries_returns_last_brightness(self):
        """When current time is past all entries, return last entry's brightness."""
        base_time = int(time.time()) - 7200  # 2 hours ago
        
        entries = [
            {"unix_time": base_time, "warm": 0.3, "cool": 0.2, "label": "first"},
            {"unix_time": base_time + 3600, "warm": 0.8, "cool": 0.6, "label": "last"}
        ]
        
        mock_schedule = create_mock_schedule_manager(entries)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        warm, cool = engine.get_current_target()
        
        # Should return last entry's brightness
        assert warm == 0.8
        assert cool == 0.6

    def test_before_first_entry_returns_first_brightness(self):
        """When current time is before first entry, return first entry's brightness."""
        base_time = int(time.time()) + 7200  # 2 hours in future
        
        entries = [
            {"unix_time": base_time, "warm": 0.5, "cool": 0.4, "label": "first"},
            {"unix_time": base_time + 3600, "warm": 0.9, "cool": 0.7, "label": "second"}
        ]
        
        mock_schedule = create_mock_schedule_manager(entries)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        warm, cool = engine.get_current_target()
        
        # Should return first entry's brightness
        assert warm == 0.5
        assert cool == 0.4

    def test_update_sets_led_brightness(self):
        """update() should call set_brightness on LED driver."""
        base_time = int(time.time()) + 3600  # 1 hour in future
        
        entries = [
            {"unix_time": base_time, "warm": 0.7, "cool": 0.5, "label": "entry"}
        ]
        
        mock_schedule = create_mock_schedule_manager(entries)
        led = LEDDriver(warm_pin=10, cool_pin=20)
        engine = TransitionEngine(mock_schedule, led)
        
        engine.update()
        
        # LED should have been set to first entry's brightness (before first entry)
        warm, cool = led.get_brightness()
        assert warm == 0.7
        assert cool == 0.5
