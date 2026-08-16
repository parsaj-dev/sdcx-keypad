"""The command layer: everything in docs/PROTOCOL.md §3, typed.

Wire format is [group, sub, ...args] padded to 64 bytes, no checksum. Group
0x06 is configuration; the firmware-update groups (0x55, 0x5A) are deliberately
not implemented — see docs/PROTOCOL.md §5.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, asdict
from typing import Iterable

from .device import DeviceInfo, SdcxError, Transport, enumerate_devices
from .layouts import Layout, get_layout

GROUP_CONFIG = 0x06

# Sub-commands of group 0x06.
CMD_GET_KEYBOARD_CONFIG = 5
CMD_GET_KEY_INFOS = 7
CMD_GET_KEYMAP = 8
CMD_SET_KEYMAP_BULK = 9
CMD_GET_LIGHT = 10
CMD_SET_LIGHT = 11
CMD_GET_MACRO = 12
CMD_SET_MACRO = 13
CMD_RESET = 15
CMD_SET_KEY_SINGLE = 16
CMD_SET_KEY_RGB_BULK = 18
CMD_GET_KEY_RGB = 19
CMD_SET_KEY_RGB_SINGLE = 20
CMD_GET_MODE_DEFAULTS = 22
CMD_SET_URL = 64
CMD_GET_URL = 65
CMD_SET_PROFILE = 251
CMD_SET_SLEEP = 252

RESET_MACROS = 4
RESET_FACTORY = 255

MAX_BRIGHTNESS = 4
MAX_SPEED = 4


def u16le(value: int) -> list[int]:
    """The bundle's T() helper: 16-bit little-endian split, used for all offsets."""
    return [value & 0xFF, (value >> 8) & 0xFF]


def _u16(lo: int, hi: int) -> int:
    return lo | (hi << 8)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass
class LightConfig:
    """The 11-byte lighting block.

    Hue/saturation/value are stored on the wire as 0-255 but are exposed here in
    the human units the vendor UI uses: hue in degrees, saturation and value in
    percent. Conversion is lossy in the same way the vendor app's is.
    """

    type: int = 1
    mode: int = 0
    brightness: int = 0
    speed: int = 0
    direction: int = 0
    color: int = 0  # 0 = rainbow/palette, 1 = single colour
    single_color_index: int = 0
    h: int = 0  # degrees, 0-359
    s: int = 0  # percent, 0-100
    v: int = 0  # percent, 0-100

    @classmethod
    def from_wire(cls, payload: bytes) -> "LightConfig":
        return cls(
            type=payload[0],
            mode=payload[2],
            brightness=payload[3],
            speed=payload[4],
            direction=payload[5],
            color=payload[6],
            single_color_index=payload[7],
            h=payload[8] * 360 // 255,
            s=payload[9] * 100 // 255,
            v=payload[10] * 100 // 255,
        )

    def to_wire(self) -> list[int]:
        block = [
            self.type,
            0,
            self.mode,
            clamp(self.brightness, 0, MAX_BRIGHTNESS),
            clamp(self.speed, 0, MAX_SPEED),
            self.direction,
            self.color,
            0,
            clamp(self.h, 0, 359) * 255 // 360,
            clamp(self.s, 0, 100) * 255 // 100,
            clamp(self.v, 0, 100) * 255 // 100,
        ]
        # Firmware quirk: writing mode 0 with the colour flag set does not
        # reliably extinguish the LEDs. The vendor app forces it to 0 too.
        if self.mode == 0:
            block[6] = 0
        return block

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rgb(self) -> tuple[int, int, int]:
        r, g, b = colorsys.hsv_to_rgb(self.h / 360.0, self.s / 100.0, self.v / 100.0)
        return round(r * 255), round(g * 255), round(b * 255)

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.rgb


@dataclass
class KeyboardConfig:
    version: int = 0
    pid: int = 0
    firmware: int = 0
    work_mode: int = 0
    link_status: int = 0
    battery: int = 0
    charge: int = 0
    profile_count: int = 0
    profile: int = 0
    layer_count: int = 0
    layer: int = 0
    auto_sleep_time: int = 0
    serial: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Accept #rgb, #rrggbb, rrggbb."""
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise SdcxError(f"{value!r} is not a colour; expected #rrggbb")
    try:
        n = int(text, 16)
    except ValueError as exc:
        raise SdcxError(f"{value!r} is not a colour; expected #rrggbb") from exc
    return (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF


class Keypad:
    """High-level device API.

    Usage:
        with Keypad.open() as pad:
            pad.set_light_mode(0)      # lights off
    """

    def __init__(self, transport: Transport, info: DeviceInfo):
        self.transport = transport
        self.info = info
        self.layout: Layout = get_layout(info.vendor_id, info.product_id)

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def open(
        cls, path: str | None = None, vendor_id: int | None = None, product_id: int | None = None
    ) -> "Keypad":
        from .device import DeviceNotFound

        if path is not None:
            info = next(
                (d for d in enumerate_devices() if d.path == path),
                DeviceInfo(path, vendor_id or 0, product_id or 0, "manual", ""),
            )
        else:
            devices = enumerate_devices(vendor_id, product_id)
            if not devices:
                raise DeviceNotFound(
                    "no supported keypad found.\n"
                    "Check it is plugged in with: sdcx list --all"
                )
            info = devices[0]
        return cls(Transport(info.path), info)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "Keypad":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- framing -----------------------------------------------------------

    def _send(self, payload: Iterable[int]) -> None:
        self.transport.write([GROUP_CONFIG, *payload])

    def _request(self, payload: Iterable[int]) -> bytes:
        return self.transport.request([GROUP_CONFIG, *payload])

    # -- device info -------------------------------------------------------

    def get_keyboard_config(self) -> KeyboardConfig:
        resp = self._request([CMD_GET_KEYBOARD_CONFIG])
        length = resp[2]
        p = resp[5:43]
        serial = ""
        if length >= 40:
            serial = "".join(chr(b) for b in resp[21:43] if b)
        return KeyboardConfig(
            version=_u16(p[0], p[1]),
            pid=_u16(p[2], p[3]),
            firmware=_u16(p[4], p[5]),
            work_mode=p[6],
            link_status=p[7],
            battery=p[8],
            charge=p[9],
            profile_count=p[10],
            profile=p[11],
            layer_count=p[12],
            layer=p[13],
            auto_sleep_time=_u16(p[14], p[15]) if length >= 16 else 0,
            serial=serial,
        )

    # -- global lighting ---------------------------------------------------

    def get_light(self) -> LightConfig:
        return LightConfig.from_wire(self._request([CMD_GET_LIGHT])[5:16])

    def set_light(self, config: LightConfig) -> None:
        block = config.to_wire()
        self._send([CMD_SET_LIGHT, len(block), 0, 0, *block])

    def get_mode_defaults(self, mode: int) -> LightConfig:
        """Ask the firmware for its preferred settings for a mode.

        The vendor UI does this on every effect change, then overwrites the mode
        byte and writes the block straight back. Following the same sequence is
        what makes a mode switch here behave identically to the vendor app,
        rather than carrying over a speed or direction the effect never uses.
        """
        resp = self._request([CMD_GET_MODE_DEFAULTS, 0, 0, 0, 1, 0, mode])
        config = LightConfig.from_wire(resp[5:16])
        config.mode = mode
        return config

    def set_light_mode(self, mode: int) -> LightConfig:
        """Switch effect, adopting the firmware's defaults for it."""
        config = self.get_mode_defaults(mode)
        self.set_light(config)
        return config

    def off(self) -> None:
        """Extinguish the LEDs, leaving the keys working. Persists in flash."""
        self.set_light(LightConfig(type=1, mode=0))

    # -- per-key colour ----------------------------------------------------

    def set_key_color(self, key_index: int, rgb: tuple[int, int, int]) -> None:
        """Set one key's colour in a single transfer, with no read-back.

        This is the fast path a host-driven effect uses. The device must be in
        light mode 5 (Custom) or the on-device effect engine repaints over it.
        """
        r, g, b = rgb
        offset = key_index * 3
        self._send([CMD_SET_KEY_RGB_SINGLE, 3, *u16le(offset), 0, 0, 0, r, g, b])

    def set_key_colors(self, colors: dict[int, tuple[int, int, int]]) -> None:
        """Write many key colours as bulk chunks.

        Colours are a flat 3-bytes-per-key table indexed by key_index, so a
        sparse update still has to send the span it touches. Keys absent from
        `colors` keep whatever the device already had.
        """
        if not colors:
            return
        existing = self.get_key_colors()
        existing.update(colors)
        highest = max(existing)
        table = bytearray(3 * (highest + 1))
        for index, (r, g, b) in existing.items():
            table[3 * index : 3 * index + 3] = bytes((r, g, b))

        total = len(table)
        sent = 0
        chunk_index = 0
        while sent < total:
            chunk = table[sent : sent + 56]
            header_len = 59
            if sent + len(chunk) >= total and total % 56 > 0:
                header_len = total % 56 + 3
            self._send(
                [
                    CMD_SET_KEY_RGB_BULK,
                    header_len,
                    *u16le(56 * chunk_index),
                    0,
                    0,
                    0,
                    *chunk,
                ]
            )
            sent += len(chunk)
            chunk_index += 1

    def get_key_colors(self) -> dict[int, tuple[int, int, int]]:
        """Read the per-key colour table for every addressable key."""
        keys = self.layout.keys
        if not keys:
            return {}
        span = (max(k.index for k in keys) + 1) * 3
        data = bytearray()
        offset = 0
        while len(data) < span:
            resp = self._request([CMD_GET_KEY_RGB, 58, *u16le(offset)])
            data.extend(resp[8:64])
            offset += 56
        return {
            k.index: (data[3 * k.index], data[3 * k.index + 1], data[3 * k.index + 2])
            for k in keys
            if 3 * k.index + 2 < len(data)
        }

    # -- profiles and power ------------------------------------------------

    def set_profile(self, profile: int) -> None:
        self._send([CMD_SET_PROFILE, profile])

    def set_auto_sleep(self, seconds: int) -> None:
        self._send([CMD_SET_SLEEP, 2, 0, 0, *u16le(seconds)])

    def reset_macros(self) -> None:
        self._send([CMD_RESET, RESET_MACROS])

    def restore_factory_settings(self, confirm: bool = False) -> None:
        """Discards the keymap, macros and colours. Requires confirm=True."""
        if not confirm:
            raise SdcxError(
                "restore_factory_settings() erases the keymap, macros and colours; "
                "pass confirm=True if that is what you want"
            )
        self._send([CMD_RESET, RESET_FACTORY])
