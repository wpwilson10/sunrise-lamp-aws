"""Property-based tests for LED Driver module.

Uses hypothesis for property-based testing with minimum 100 iterations per property.
"""

import pytest
from hypothesis import given, settings, strategies as st

from led_driver import LEDDriver


class TestLEDDriverProperties:
    """Property-based tests for LEDDriver class."""

    @settings(max_examples=100)
    @given(
        warm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        cool=st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    )
    def test_brightness_state_round_trip(self, warm, cool):
        """Property 1: Brightness State Round-Trip
        
        For any perceived brightness value (warm, cool) in the range [0.0, 1.0],
        setting the LED brightness and then getting the brightness should return
        the same values.
        
        Feature: lamp-controller-refactor, Property 1: Brightness State Round-Trip
        Validates: Requirements 2.1, 2.5
        """
        led = LEDDriver(warm_pin=10, cool_pin=20)
        led.set_brightness(warm, cool)
        result = led.get_brightness()
        assert result == (warm, cool)

    @settings(max_examples=100)
    @given(brightness=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    def test_gamma_correction_formula(self, brightness):
        """Property 2: Gamma Correction Formula
        
        For any perceived brightness value in the range [0.0, 1.0], the computed
        PWM duty cycle should equal round(65535 * brightness^2.2).
        
        Feature: lamp-controller-refactor, Property 2: Gamma Correction Formula
        Validates: Requirements 2.7
        """
        led = LEDDriver(warm_pin=10, cool_pin=20)
        duty = led._to_duty_cycle(brightness)
        expected = round(65535 * (brightness ** 2.2))
        assert duty == expected
