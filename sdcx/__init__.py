"""Linux driver for SDCX / SDINNOVATION programmable keypads.

Protocol reverse-engineered from the vendor's WebHID configurator; see
docs/PROTOCOL.md. Pure standard library — the config interface is a plain
64-byte hidraw channel, so no HID binding is needed.
"""

from .device import (
    DeviceInfo,
    DeviceNotFound,
    PermissionDenied,
    SdcxError,
    Transport,
    enumerate_devices,
)
from .layouts import Layout, LightMode, get_layout, is_supported
from .protocol import Keypad, KeyboardConfig, LightConfig, parse_hex_color

__version__ = "0.1.0"
__all__ = [
    "DeviceInfo", "DeviceNotFound", "PermissionDenied", "SdcxError", "Transport",
    "enumerate_devices", "Layout", "LightMode", "get_layout", "is_supported",
    "Keypad", "KeyboardConfig", "LightConfig", "parse_hex_color", "__version__",
]
