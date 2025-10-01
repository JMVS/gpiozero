# vim: set fileencoding=utf-8:
#
# GPIO Zero: a library for controlling the Raspberry Pi's GPIO pins
#
# Copyright (c) 2025 [Jose Vera] <jose.veramutka+gh@gmail.com>
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Pin factory for WiringPi, providing support for Orange Pi and other
single-board computers.

.. note::
    This factory requires WiringPi to be installed. For Orange Pi, install
    wiringOP from https://github.com/orangepi-xunlong/wiringOP
    
    Pin numbering uses WiringPi's scheme. Use ``gpio readall`` to see the
    pin mapping on your board.
"""

from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
)

import subprocess
from threading import Lock
from time import monotonic
from collections import defaultdict

from . import Factory, Pin
from ..exc import (
    PinInvalidPin,
    PinInvalidFunction,
    PinSetInput,
    PinInvalidPull,
    PinInvalidState,
    PinPWMUnsupported,
    PinEdgeDetectUnsupported,
)


class WiringPiFactory(Factory):
    """
    Uses WiringPi's ``gpio`` command-line utility to interface with GPIO pins.
    This factory provides support for Orange Pi and other boards using WiringPi.

    You can construct WiringPi pins manually like this::

        from gpiozero.pins.wiringpi import WiringPiFactory
        from gpiozero import LED

        factory = WiringPiFactory()
        led = LED(2, pin_factory=factory)  # WiringPi pin 2

    .. note::
        Pin numbers use WiringPi's numbering scheme, not GPIO or physical
        numbers. Use ``gpio readall`` to see the mapping on your board.

    .. warning::
        This implementation does not support PWM or edge detection. Attempting
        to use these features will raise appropriate exceptions.
    """

    def __init__(self):
        super(WiringPiFactory, self).__init__()
        self._pins = {}
        self._pin_lock = Lock()
        self._board_info = None
        
        # Verify WiringPi is available
        try:
            subprocess.run(
                ['gpio', '-v'],
                check=True,
                capture_output=True,
                timeout=5
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            raise IOError(
                'WiringPi not found. For Orange Pi, install wiringOP: '
                'https://github.com/orangepi-xunlong/wiringOP'
            )

    def close(self):
        """Close all pins and clean up."""
        super(WiringPiFactory, self).close()
        with self._pin_lock:
            pins = list(self._pins.values())
            self._pins.clear()
        for pin in pins:
            try:
                pin.close()
            except:
                pass

    def pin(self, spec):
        """
        Create a pin instance for the given specification.
        
        :param spec: Pin number in WiringPi numbering scheme
        """
        with self._pin_lock:
            if isinstance(spec, str):
                try:
                    spec = int(spec)
                except ValueError:
                    raise PinInvalidPin('invalid pin specification: {0}'.format(spec))
            
            if spec not in self._pins:
                self._pins[spec] = WiringPiPin(self, spec)
            
            return self._pins[spec]

    def _get_board_info(self):
        """Get board information."""
        if self._board_info is None:
            try:
                with open('/proc/device-tree/model', 'r') as f:
                    model = f.read().strip().rstrip('\x00')
            except:
                model = 'WiringPi-compatible board'
            
            from .data import BoardInfo
            
            self._board_info = BoardInfo(
                revision='wiringpi',
                model=model,
                pcb_revision='1.0',
                released='Unknown',
                soc='Unknown',
                manufacturer='Unknown',
                memory=1024,
                storage='SD',
                usb=2,
                usb3=0,
                ethernet=1,
                eth_speed=100,
                wifi=False,
                bluetooth=False,
                csi=0,
                dsi=0,
                headers={},
                board=''
            )
        
        return self._board_info

    def ticks(self):
        """Return current monotonic time."""
        return monotonic()

    def ticks_diff(self, later, earlier):
        """Calculate difference between two tick values."""
        return later - earlier


class WiringPiPin(Pin):
    """
    Pin implementation for WiringPi. See :class:`WiringPiFactory` for more
    information.
    """

    def __init__(self, factory, number):
        super(WiringPiPin, self).__init__(factory, number)
        self._number = number
        self._factory = factory
        self._function = 'input'
        self._state = 0
        self._pull = 'floating'
        self._bounce = None
        self._edges = 'none'
        self._when_changed = None
        self._lock = Lock()
        
        # Initialize as input
        self._execute(['gpio', 'mode', str(self._number), 'in'])

    def _execute(self, cmd):
        """Execute a WiringPi gpio command."""
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise IOError('WiringPi command failed: {0}'.format(e))
        except subprocess.TimeoutExpired:
            raise IOError('WiringPi command timed out')

    def close(self):
        """Clean up pin resources."""
        if self._when_changed is not None:
            self.when_changed = None
        self.frequency = None
        # Set back to input
        try:
            with self._lock:
                self._execute(['gpio', 'mode', str(self._number), 'in'])
        except:
            pass

    def output_with_state(self, state):
        """Set pin to output with initial state."""
        with self._lock:
            self._pull = 'floating'
            self._execute(['gpio', 'mode', str(self._number), 'out'])
            self._execute(['gpio', 'write', str(self._number), str(int(bool(state)))])
            self._function = 'output'
            self._state = int(bool(state))

    def input_with_pull(self, pull):
        """Set pin to input with pull resistor."""
        if pull not in ('floating', 'up', 'down'):
            raise PinInvalidPull('invalid pull "{0}" for pin {1}'.format(pull, self))
        with self._lock:
            if pull == 'up':
                self._execute(['gpio', 'mode', str(self._number), 'up'])
            elif pull == 'down':
                self._execute(['gpio', 'mode', str(self._number), 'down'])
            else:
                self._execute(['gpio', 'mode', str(self._number), 'in'])
            self._function = 'input'
            self._pull = pull

    def _get_function(self):
        """Get current pin function."""
        return self._function

    def _set_function(self, value):
        """Set pin function (input/output)."""
        if value not in ('input', 'output'):
            raise PinInvalidFunction(
                'invalid function "{0}" for pin {1}'.format(value, self))
        with self._lock:
            if value == 'input':
                self._execute(['gpio', 'mode', str(self._number), 'in'])
            else:
                self._pull = 'floating'
                self._execute(['gpio', 'mode', str(self._number), 'out'])
            self._function = value

    def _get_state(self):
        """Get current pin state."""
        with self._lock:
            if self._function == 'output':
                return self._state
            result = self._execute(['gpio', 'read', str(self._number)])
            return int(result)

    def _set_state(self, value):
        """Set pin state."""
        with self._lock:
            if self._function != 'output':
                raise PinSetInput('cannot set state of pin {0}'.format(self))
            try:
                state = int(bool(value))
                self._execute(['gpio', 'write', str(self._number), str(state)])
                self._state = state
            except (ValueError, TypeError):
                raise PinInvalidState(
                    'invalid state "{0}" for pin {1}'.format(value, self))

    def _get_pull(self):
        """Get pull resistor setting."""
        return self._pull

    def _set_pull(self, value):
        """Set pull resistor."""
        if self._function != 'input':
            raise PinInvalidPull('cannot set pull on non-input pin {0}'.format(self))
        if value not in ('floating', 'up', 'down'):
            raise PinInvalidPull('invalid pull "{0}" for pin {1}'.format(value, self))
        with self._lock:
            if value == 'up':
                self._execute(['gpio', 'mode', str(self._number), 'up'])
            elif value == 'down':
                self._execute(['gpio', 'mode', str(self._number), 'down'])
            else:
                self._execute(['gpio', 'mode', str(self._number), 'in'])
            self._pull = value

    def _get_frequency(self):
        """PWM frequency (not supported)."""
        return None

    def _set_frequency(self, value):
        """Set PWM frequency (not supported)."""
        if value is not None:
            raise PinPWMUnsupported('PWM is not supported on pin {0}'.format(self))

    def _get_bounce(self):
        """Get bounce time for edge detection."""
        return self._bounce

    def _set_bounce(self, value):
        """Set bounce time (not supported)."""
        if value is not None:
            raise PinEdgeDetectUnsupported(
                'edge detection is not supported on pin {0}'.format(self))
        self._bounce = value

    def _get_edges(self):
        """Get edge detection mode."""
        return self._edges

    def _set_edges(self, value):
        """Set edge detection mode (not supported)."""
        if value != 'none':
            raise PinEdgeDetectUnsupported(
                'edge detection is not supported on pin {0}'.format(self))
        self._edges = value

    def _get_when_changed(self):
        """Get when_changed callback."""
        return self._when_changed

    def _set_when_changed(self, value):
        """Set when_changed callback (not supported)."""
        if value is not None:
            raise PinEdgeDetectUnsupported(
                'edge detection is not supported on pin {0}'.format(self))
        self._when_changed = value

    def __repr__(self):
        return 'WiringPi{0}'.format(self._number)
