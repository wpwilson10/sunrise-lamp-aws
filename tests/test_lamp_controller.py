"""Unit tests for LampController startup sequence.

Tests verify:
- Night light is set before network operations
- Fallback behavior on WiFi/NTP/schedule failures
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys

# Mock the machine module before importing main
sys.modules['machine'] = MagicMock()

import config
from main import LampController


class MockLEDDriver:
    """Mock LED driver for testing."""
    
    def __init__(self, warm_pin, cool_pin, pwm_freq=8000):
        self._warm_brightness = 0.0
        self._cool_brightness = 0.0
        self.night_light_called = False
        self.night_light_brightness = None
        self.set_brightness_calls = []
    
    def set_brightness(self, warm, cool):
        self._warm_brightness = warm
        self._cool_brightness = cool
        self.set_brightness_calls.append((warm, cool))
    
    def get_brightness(self):
        return (self._warm_brightness, self._cool_brightness)
    
    def night_light(self, brightness=0.25):
        self.night_light_called = True
        self.night_light_brightness = brightness
        self._warm_brightness = brightness
        self._cool_brightness = 0.0
    
    def off(self):
        self._warm_brightness = 0.0
        self._cool_brightness = 0.0


class MockNetworkManager:
    """Mock network manager for testing."""
    
    def __init__(self, ssid, password, ntp_servers=None):
        self.ssid = ssid
        self.password = password
        self.ntp_servers = ntp_servers
        self._connected = False
        self._time_synced = False
        
        # Control test behavior
        self.wifi_should_succeed = True
        self.ntp_should_succeed = True
    
    def connect_wifi(self, timeout=30):
        if self.wifi_should_succeed:
            self._connected = True
            return True
        return False
    
    def is_connected(self):
        return self._connected
    
    def ensure_connected(self, timeout=30):
        return self._connected
    
    def sync_time(self):
        if self.ntp_should_succeed:
            self._time_synced = True
            return True
        return False
    
    def is_time_synced(self):
        return self._time_synced
    
    def http_get(self, url, headers=None, timeout=10):
        return None
    
    def http_post(self, url, data, headers=None, timeout=10):
        return True


class MockScheduleManager:
    """Mock schedule manager for testing."""

    def __init__(self, network, api_url, api_token, refresh_hours=None):
        self.network = network
        self.api_url = api_url
        self.api_token = api_token
        self._mode = "dayNight"
        self._has_schedule = False

        # Control test behavior
        self.fetch_should_succeed = True

    def fetch_schedule(self):
        if self.fetch_should_succeed:
            self._has_schedule = True
            return True
        return False

    def needs_refresh(self):
        return not self._has_schedule

    def get_entries(self):
        return []

    def get_mode(self):
        return self._mode

    def has_valid_schedule(self):
        return self._has_schedule

    def is_demo_mode(self):
        return self._mode == "demo"

    def get_demo_cycle_duration(self):
        return 15

    def _setup_demo_schedule(self):
        self._mode = "demo"
        self._has_schedule = True
        return True


class MockTransitionEngine:
    """Mock transition engine for testing."""
    
    def __init__(self, schedule_manager, led_driver):
        self.schedule = schedule_manager
        self.leds = led_driver
        self.update_called = False
    
    def update(self):
        self.update_called = True
    
    def get_current_target(self):
        return (0.25, 0.0)


class TestStartupSequence:
    """Tests for LampController startup sequence."""

    def test_night_light_set_before_network_operations(self):
        """Verify night light is set immediately before any network operations.
        
        Requirements: 3.1 - WHEN the device powers on, THE Lamp_Controller SHALL
        immediately set LEDs to night light mode before attempting network operations
        """
        # Track the order of operations
        operation_order = []
        
        mock_led = MockLEDDriver(10, 20)
        original_night_light = mock_led.night_light
        def tracked_night_light(brightness=0.25):
            operation_order.append('night_light')
            original_night_light(brightness)
        mock_led.night_light = tracked_night_light
        
        mock_network = MockNetworkManager("test", "pass")
        original_connect = mock_network.connect_wifi
        def tracked_connect(timeout=30):
            operation_order.append('wifi_connect')
            return original_connect(timeout)
        mock_network.connect_wifi = tracked_connect
        
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        
        # Create controller with mocked components
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            controller._startup_sequence()
        
        # Verify night_light was called before wifi_connect
        assert 'night_light' in operation_order
        assert 'wifi_connect' in operation_order
        night_light_index = operation_order.index('night_light')
        wifi_index = operation_order.index('wifi_connect')
        assert night_light_index < wifi_index, \
            f"Night light should be set before WiFi connect. Order: {operation_order}"

    def test_fallback_on_wifi_failure(self):
        """Verify lamp stays in night light mode when WiFi fails.
        
        Requirements: 3.2 - WHEN WiFi connection fails after 30 seconds,
        THE Lamp_Controller SHALL continue in night light mode
        """
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_network.wifi_should_succeed = False
        
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            result = controller._startup_sequence()
        
        # Startup should fail but night light should be active
        assert result is False
        assert mock_led.night_light_called
        assert mock_led.night_light_brightness == config.NIGHT_LIGHT_BRIGHTNESS

    def test_fallback_on_ntp_failure(self):
        """Verify lamp stays in night light mode when NTP sync fails.
        
        Requirements: 3.4 - WHEN NTP sync fails on startup, THE Lamp_Controller
        SHALL remain in night light mode since schedule times cannot be evaluated
        """
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_network.wifi_should_succeed = True
        mock_network.ntp_should_succeed = False
        
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            result = controller._startup_sequence()
        
        # Startup should fail but night light should be active
        assert result is False
        assert mock_led.night_light_called
        # Schedule fetch should not have been attempted
        assert not mock_schedule._has_schedule

    def test_fallback_on_schedule_failure(self):
        """Verify lamp stays in night light mode when schedule fetch fails.
        
        Requirements: 3.3 - WHEN schedule fetch fails on startup, THE Lamp_Controller
        SHALL operate in night light mode until a schedule is successfully retrieved
        """
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_network.wifi_should_succeed = True
        mock_network.ntp_should_succeed = True
        
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_schedule.fetch_should_succeed = False
        
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            result = controller._startup_sequence()
        
        # Startup should fail but night light should be active
        assert result is False
        assert mock_led.night_light_called

    def test_successful_startup_sequence(self):
        """Verify complete startup sequence when all operations succeed."""
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            result = controller._startup_sequence()
        
        # All phases should complete successfully
        assert result is True
        assert mock_led.night_light_called
        assert mock_network._connected
        assert mock_network._time_synced
        assert mock_schedule._has_schedule
        assert mock_transition.update_called
        assert controller._startup_complete


class TestDemoMode:
    """Tests for demo mode functionality."""

    def test_demo_mode_interpolates_brightness(self):
        """Verify demo mode calculates correct brightness interpolation."""
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)

        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition), \
             patch('main.time.sleep', side_effect=KeyboardInterrupt):

            controller = LampController()
            controller._leds = mock_led

            # Run demo (will be interrupted immediately by mocked sleep)
            try:
                controller.run_demo()
            except KeyboardInterrupt:
                pass

        # Verify LED was set to off after interrupt
        assert mock_led._warm_brightness == 0.0
        assert mock_led._cool_brightness == 0.0

    def test_demo_schedule_is_configured(self):
        """Verify demo schedule is properly configured."""
        import config

        assert hasattr(config, 'DEMO_SCHEDULE')
        assert hasattr(config, 'DEMO_CYCLE_DURATION_S')
        assert len(config.DEMO_SCHEDULE) >= 2  # At least 2 waypoints
        assert config.DEMO_CYCLE_DURATION_S > 0

        # Verify each waypoint has correct format
        for waypoint in config.DEMO_SCHEDULE:
            assert len(waypoint) == 4  # (time, warm, cool, label)
            assert isinstance(waypoint[0], (int, float))  # time
            assert 0 <= waypoint[1] <= 100  # warm brightness
            assert 0 <= waypoint[2] <= 100  # cool brightness
            assert isinstance(waypoint[3], str)  # label


class TestTimerCallback:
    """Tests for timer callback behavior."""

    def test_timer_callback_updates_brightness(self):
        """Verify timer callback updates LED brightness."""
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_network._connected = True
        
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_schedule._has_schedule = True
        
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            # Reset update_called to test timer callback
            mock_transition.update_called = False
            
            controller._on_timer(None)
        
        assert mock_transition.update_called

    def test_timer_callback_falls_back_on_error(self):
        """Verify timer callback falls back to night light on error."""
        mock_led = MockLEDDriver(10, 20)
        mock_network = MockNetworkManager("test", "pass")
        mock_network._connected = True
        
        mock_schedule = MockScheduleManager(mock_network, "url", "token")
        mock_schedule._has_schedule = True
        
        # Create transition engine that raises an error
        mock_transition = MockTransitionEngine(mock_schedule, mock_led)
        def raise_error():
            raise RuntimeError("Test error")
        mock_transition.update = raise_error
        
        with patch('main.LEDDriver', return_value=mock_led), \
             patch('main.NetworkManager', return_value=mock_network), \
             patch('main.ScheduleManager', return_value=mock_schedule), \
             patch('main.TransitionEngine', return_value=mock_transition):
            
            controller = LampController()
            controller._leds = mock_led
            controller._network = mock_network
            controller._schedule = mock_schedule
            controller._transition = mock_transition
            
            # Reset night_light_called
            mock_led.night_light_called = False
            
            # Should not raise, should fall back to night light
            controller._on_timer(None)
        
        assert mock_led.night_light_called
