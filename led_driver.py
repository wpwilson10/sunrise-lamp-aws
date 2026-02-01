"""LED Driver module for controlling warm and cool LED channels.

This module encapsulates PWM control and brightness state tracking for the
Sunrise Lamp Controller. It maintains internal brightness state to prevent
sudden jumps during transitions.

Gamma Correction:
-----------------
The module applies gamma correction (γ = 2.2) when converting perceived
brightness to PWM duty cycles. This is essential because:

1. Human brightness perception is logarithmic, not linear
2. A 50% PWM duty cycle appears ~73% as bright to human eyes
3. Without correction, low brightness values appear too bright and
   transitions look uneven

The gamma correction formula (brightness^2.2) maps perceived brightness
to the physical light output needed for correct visual perception. This
ensures smooth, perceptually uniform transitions across the full range.

For more details, see:
- https://codeinsecurity.wordpress.com/2023/07/17/the-problem-with-driving-leds-with-pwm/
- https://en.wikipedia.org/wiki/Gamma_correction
"""

from __future__ import annotations

try:
    import machine
    from machine import PWM, Pin
except ImportError:
    # For desktop testing, machine module won't be available
    machine = None
    PWM = None
    Pin = None

try:
    import config
except ImportError:
    config = None


class LEDDriver:
    """Controls warm and cool LED channels with brightness state tracking.

    Maintains internal perceived brightness state (0.0-1.0) and applies
    gamma correction when converting to PWM duty cycle.

    Attributes:
        _warm_brightness: Current perceived warm brightness (0.0-1.0)
        _cool_brightness: Current perceived cool brightness (0.0-1.0)
        _warm_pwm: PWM object for warm LED channel
        _cool_pwm: PWM object for cool LED channel
    """

    def __init__(self, warm_pin: int, cool_pin: int, pwm_freq: int = 8000) -> None:
        """Initialize PWM channels and brightness state.

        Args:
            warm_pin: GPIO pin number for warm LED channel
            cool_pin: GPIO pin number for cool LED channel
            pwm_freq: PWM frequency in Hz (default 8000)
        """
        self._warm_brightness = 0.0
        self._cool_brightness = 0.0

        if machine is not None:
            self._warm_pwm = machine.PWM(machine.Pin(warm_pin))
            self._warm_pwm.freq(pwm_freq)
            self._cool_pwm = machine.PWM(machine.Pin(cool_pin))
            self._cool_pwm.freq(pwm_freq)
        else:
            # Mock PWM for desktop testing
            self._warm_pwm = None
            self._cool_pwm = None

    def set_brightness(self, warm: float, cool: float) -> None:
        """Set perceived brightness (0.0-1.0) for both channels.

        Updates internal state first, then applies gamma correction
        and sets PWM duty cycle.

        Args:
            warm: Perceived brightness for warm channel (0.0-1.0)
            cool: Perceived brightness for cool channel (0.0-1.0)
        """
        # Clamp values to valid range
        warm = max(0.0, min(1.0, warm))
        cool = max(0.0, min(1.0, cool))

        # Update internal state before applying PWM changes
        self._warm_brightness = warm
        self._cool_brightness = cool

        # Apply gamma correction and set PWM
        if self._warm_pwm is not None:
            self._warm_pwm.duty_u16(self._to_duty_cycle(warm))
        if self._cool_pwm is not None:
            self._cool_pwm.duty_u16(self._to_duty_cycle(cool))

    def get_brightness(self) -> tuple[float, float]:
        """Return current (warm, cool) perceived brightness from internal state.

        Returns:
            Tuple of (warm_brightness, cool_brightness) in range 0.0-1.0
        """
        return (self._warm_brightness, self._cool_brightness)

    def _to_duty_cycle(self, brightness: float) -> int:
        """Convert perceived brightness to PWM duty cycle with gamma correction.

        Human perception of brightness is non-linear - we perceive brightness
        changes logarithmically rather than linearly. A 50% PWM duty cycle
        appears much brighter than 50% perceived brightness to the human eye.

        Gamma correction compensates for this by applying a power function
        (gamma = 2.2) to map linear perceived brightness to the non-linear
        PWM values needed for correct visual perception. This ensures:
        - Smooth, perceptually uniform transitions
        - Accurate brightness levels matching user expectations
        - Better utilization of the full brightness range

        Without gamma correction, low brightness values would appear too bright
        and transitions would look uneven, with most visible change happening
        at the lower end of the range.

        The gamma value of 2.2 is the standard for most displays and LEDs,
        representing the approximate inverse of human brightness perception.

        References:
        - https://codeinsecurity.wordpress.com/2023/07/17/the-problem-with-driving-leds-with-pwm/
        - https://en.wikipedia.org/wiki/Gamma_correction
        - CIE 1931 color space and luminance perception studies

        Args:
            brightness: Perceived brightness value (0.0-1.0)

        Returns:
            PWM duty cycle value (0-65535) for 16-bit PWM

        Example:
            brightness=0.5 (50% perceived) -> duty=11930 (18% PWM)
            brightness=1.0 (100% perceived) -> duty=65535 (100% PWM)
        """
        gamma = config.GAMMA_CORRECTION if config else 2.2
        max_duty = config.MAX_DUTY_CYCLE if config else 65535
        return round(max_duty * (brightness ** gamma))

    def night_light(self, brightness: float = 0.25) -> None:
        """Set night light mode (warm only at specified brightness).

        Args:
            brightness: Warm LED brightness level (default 0.25)
        """
        self.set_brightness(brightness, 0.0)

    def off(self) -> None:
        """Turn off both channels."""
        self.set_brightness(0.0, 0.0)
