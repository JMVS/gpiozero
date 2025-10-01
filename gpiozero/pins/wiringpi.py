# -*- coding: utf-8 -*-

"""
Pin factory implementation for WiringPi, providing support for Orange Pi
and other single-board computers that use WiringPi for GPIO control.

This module provides the :class:`WiringPiFactory` class which allows gpiozero
to work with Orange Pi and other boards that use WiringPi instead of RPi.GPIO.
"""

from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
)

import subprocess
import atexit
from threading import Lock
from collections import namedtuple

from .local import LocalPiFactory, LocalPiPin
from ..exc import PinInvalidPin, PinSetInput, PinFixedPull


class WiringPiPin(LocalPiPin):
    """
    Pin implementation that uses WiringPi's gpio command-line utility.
    
    This pin class provides GPIO functionality by executing WiringPi commands
    via subprocess. It supports input/output modes, pull resistors, and
    state reading/writing.
    """
    
    def __init__(self, factory, number):
        super(WiringPiPin, self).__init__(factory, number)
        self._number = number
        self._function = 'input'
        self._state = 0
        self._pull = 'floating'
        self._bounce = None
        self._edges = 'none'
        self._lock = Lock()
        
        # Initialize pin as input by default
        self._execute(['gpio', 'mode', str(self._number), 'in'])
    
    def _execute(self, cmd):
        """
        Execute a WiringPi gpio command.
        
        :param list cmd: Command and arguments to execute
        :returns: Command output as string
        :raises IOError: If command execution fails
        """
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
            raise IOError("WiringPi gpio command failed: {}".format(e))
        except subprocess.TimeoutExpired:
            raise IOError("WiringPi gpio command timed out")
        except FileNotFoundError:
            raise IOError(
                "WiringPi 'gpio' command not found. "
                "Please install WiringPi or wiringOP for your board."
            )
    
    def close(self):
        """Release resources and set pin to input mode."""
        if not self.closed:
            try:
                self.function = 'input'
            except:
                pass
            super(WiringPiPin, self).close()
    
    def _get_function(self):
        """Get the current pin function (input/output)."""
        return self._function
    
    def _set_function(self, value):
        """
        Set the pin function.
        
        :param str value: Either 'input' or 'output'
        """
        with self._lock:
            if value not in ('input', 'output'):
                raise PinSetInput("Invalid function: {}".format(value))
            
            mode = 'out' if value == 'output' else 'in'
            self._execute(['gpio', 'mode', str(self._number), mode])
            self._function = value
    
    def _get_state(self):
        """Get the current pin state (0 or 1)."""
        with self._lock:
            if self._function == 'output':
                return self._state
            else:
                result = self._execute(['gpio', 'read', str(self._number)])
                return int(result)
    
    def _set_state(self, value):
        """
        Set the pin state.
        
        :param int value: 0 for LOW, 1 for HIGH
        """
        with self._lock:
            if self._function != 'output':
                raise PinSetInput("Cannot set state of input pin")
            
            state = 1 if value else 0
            self._execute(['gpio', 'write', str(self._number), str(state)])
            self._state = state
    
    def _get_pull(self):
        """Get the pull resistor configuration."""
        return self._pull
    
    def _set_pull(self, value):
        """
        Set the pull resistor configuration.
        
        :param str value: 'floating', 'up', or 'down'
        """
        with self._lock:
            if value not in ('floating', 'up', 'down'):
                raise PinFixedPull("Invalid pull: {}".format(value))
            
            if value == 'up':
                self._execute(['gpio', 'mode', str(self._number), 'up'])
            elif value == 'down':
                self._execute(['gpio', 'mode', str(self._number), 'down'])
            else:
                self._execute(['gpio', 'mode', str(self._number), 'in'])
            
            self._pull = value
    
    def _get_frequency(self):
        """PWM frequency is not supported in this implementation."""
        return None
    
    def _set_frequency(self, value):
        """PWM frequency setting is not supported."""
        pass
    
    def _get_bounce(self):
        """Get the bounce time for edge detection."""
        return self._bounce
    
    def _set_bounce(self, value):
        """Set the bounce time for edge detection."""
        self._bounce = value
    
    def _get_edges(self):
        """Get the edge detection configuration."""
        return self._edges
    
    def _set_edges(self, value):
        """
        Set edge detection (not fully implemented).
        
        :param str value: 'none', 'rising', 'falling', or 'both'
        """
        self._edges = value


class WiringPiFactory(LocalPiFactory):
    """
    Factory for creating WiringPi-based pins.
    
    This factory enables gpiozero to work with boards that use WiringPi
    for GPIO control, such as Orange Pi, Banana Pi, and other compatible
    single-board computers.
    
    Pin numbering uses WiringPi's numbering scheme. Use ``gpio readall``
    to see the pin mapping on your board.
    
    Example usage::
    
        from gpiozero import Device, LED
        from gpiozero.pins.wiringpi import WiringPiFactory
        
        Device.pin_factory = WiringPiFactory()
        led = LED(2)  # WiringPi pin 2
        led.on()
    
    .. note::
        Requires WiringPi to be installed on the system. For Orange Pi,
        install wiringOP from https://github.com/orangepi-xunlong/wiringOP
    """
    
    def __init__(self):
        super(WiringPiFactory, self).__init__()
        self._pins = {}
        self._pin_lock = Lock()
        
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
                "WiringPi not found or not working. "
                "For Orange Pi, install wiringOP: "
                "https://github.com/orangepi-xunlong/wiringOP"
            )
        
        atexit.register(self.close)
    
    def _get_revision(self):
        """Return a fake revision code for compatibility."""
        return 'a02082'
    
    def _get_pi_info(self):
        """
        Get information about the board.
        
        Attempts to read from device tree, falls back to generic info.
        """
        try:
            with open('/proc/device-tree/model', 'r') as f:
                model = f.read().strip().rstrip('\x00')
        except:
            model = "WiringPi-compatible board"
        
        # Return a namedtuple compatible with gpiozero's expectations
        PiBoardInfo = namedtuple('PiBoardInfo', [
            'revision', 'model', 'pcb_revision', 'released',
            'soc', 'manufacturer', 'memory', 'storage',
            'usb', 'usb3', 'ethernet', 'wifi', 'bluetooth',
            'csi', 'dsi', 'headers'
        ])
        
        return PiBoardInfo(
            revision='a02082',
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
            wifi=False,
            bluetooth=False,
            csi=0,
            dsi=0,
            headers={}
        )
    
    def pin(self, spec):
        """
        Get or create a pin.
        
        :param spec: Pin specification (WiringPi pin number)
        :returns: WiringPiPin instance
        """
        with self._pin_lock:
            # Convert to int if string
            if isinstance(spec, str):
                try:
                    spec = int(spec)
                except ValueError:
                    raise PinInvalidPin("Invalid pin specification: {}".format(spec))
            
            # Get or create pin
            if spec not in self._pins:
                self._pins[spec] = WiringPiPin(self, spec)
            
            return self._pins[spec]
    
    def release_pins(self, *pins):
        """
        Release pins for external control.
        
        This is a no-op for WiringPi as multiple processes can control
        the same pins simultaneously.
        """
        pass
    
    def close(self):
        """Close all pins and clean up resources."""
        with self._pin_lock:
            pins_to_close = list(self._pins.values())
            self._pins.clear()
        
        for pin in pins_to_close:
            try:
                pin.close()
            except:
                pass
        
        super(WiringPiFactory, self).close()
