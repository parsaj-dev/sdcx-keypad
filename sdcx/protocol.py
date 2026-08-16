"""The command layer: everything in docs/PROTOCOL.md §3, typed.

Wire format is [group, sub, ...args] padded to 64 bytes, no checksum. Group
0x06 is configuration; the firmware-update groups (0x55, 0x5A) are deliberately
not implemented; see docs/PROTOCOL.md §5.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, asdict, field
from typing import Iterable

from .device import DeviceInfo, SdcxError, Transport, enumerate_devices
from .keycodes import Keycode, describe, parse_keycode
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

# The macro area is a fixed 4096-byte blob: a 64-byte index of u16le pointers
# followed by the step lists they point at. See MacroBlob below.
MACRO_AREA_SIZE = 4096
MACRO_INDEX_SIZE = 64
MACRO_SLOTS = MACRO_INDEX_SIZE // 2
MACRO_STEP_SIZE = 4

# Reads chunk at 56 data bytes because that is what fits after the 8-byte
# response header. Macro *writes* chunk at 59, because the write frame has no header
# beyond [group, sub, off_lo, off_hi], so three more bytes fit. The vendor app
# uses exactly these two numbers and mixing them up silently corrupts the blob.
READ_CHUNK = 56
MACRO_WRITE_CHUNK = 59


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


@dataclass
class KeyAssignment:
    """What one key does, as the four bytes the firmware stores.

    `name` is the round-trippable rendering of those bytes: feed it back to
    `sdcx keymap set` and you get the same assignment. It is derived, not read
    from the device: the firmware stores no names.
    """

    key_index: int
    type: int
    value1: int
    value2: int
    value3: int

    @property
    def name(self) -> str:
        return describe(self.type, self.value1, self.value2, self.value3)

    @property
    def wire(self) -> list[int]:
        return [self.type, self.value1, self.value2, self.value3]

    @classmethod
    def from_keycode(cls, key_index: int, keycode: Keycode) -> "KeyAssignment":
        return cls(key_index, *keycode.wire)

    def to_dict(self) -> dict:
        return {
            "key_index": self.key_index,
            "name": self.name,
            "type": self.type,
            "wire": self.wire,
        }


# Macro step types, as stored in the low six bits of the flags byte. These are
# not the same numbers the vendor's UI uses internally (it calls them 1-4); the
# mapping below is the on-the-wire one taken from its encoder.
STEP_KEYBOARD = 2
STEP_MOUSE = 3
STEP_WHEEL_V = 4
STEP_WHEEL_H = 5

STEP_FLAG_PRESS = 0x40
STEP_FLAG_LAST = 0x80

STEP_KIND_NAMES: dict[int, str] = {
    STEP_KEYBOARD: "key",
    STEP_MOUSE: "mouse",
    STEP_WHEEL_V: "wheel",
    STEP_WHEEL_H: "hwheel",
}


@dataclass
class MacroStep:
    """One event in a macro: four bytes `[delay_lo, delay_hi, flags, code]`.

    `delay` is the pause *after* this step, in milliseconds. The vendor editor
    records it as the gap to the next event, and the last step's delay is the
    tail before the macro ends.

    `code` means whatever `kind` says: a HID usage for `key`, a button bitmask
    for `mouse`, and a signed direction (1 or 255) for the two wheel kinds.
    """

    kind: int
    code: int
    press: bool = True
    delay: int = 0

    @property
    def kind_name(self) -> str:
        return STEP_KIND_NAMES.get(self.kind, str(self.kind))

    def to_wire(self, last: bool = False) -> list[int]:
        flags = self.kind & 0x3F
        if self.press:
            flags |= STEP_FLAG_PRESS
        if last:
            flags |= STEP_FLAG_LAST
        return [*u16le(clamp(self.delay, 0, 0xFFFF)), flags, self.code & 0xFF]

    def to_dict(self) -> dict:
        return {
            "kind": self.kind_name,
            "code": self.code,
            "action": "press" if self.press else "release",
            "delay": self.delay,
        }


@dataclass
class Macro:
    """One macro slot: an ordered list of steps, or empty."""

    slot: int
    steps: list[MacroStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"slot": self.slot, "steps": [s.to_dict() for s in self.steps]}


def decode_macros(blob: bytes) -> list[Macro]:
    """Split the 4096-byte macro area into its slots.

    Layout, from the vendor bundle's encoder and decoder:

        0..63     32 u16le pointers, one per slot, into this same blob.
                  0xFFFF (and a zero low byte) mean "slot empty".
        64..4095  step lists, 4 bytes each, packed back to back in slot order.

    A step list has no length field: the last step carries bit 7 in its flags
    byte. A flags byte of 0 also terminates, which is what stops a decode
    running off the end of a freshly reset (all-zero) area.
    """
    macros: list[Macro] = []
    for slot in range(MACRO_SLOTS):
        lo, hi = blob[2 * slot], blob[2 * slot + 1]
        macro = Macro(slot)
        macros.append(macro)
        if (lo == 0xFF and hi == 0xFF) or lo == 0:
            continue
        offset = _u16(lo, hi)
        if offset >= MACRO_AREA_SIZE:
            continue
        while offset + MACRO_STEP_SIZE <= MACRO_AREA_SIZE:
            delay = _u16(blob[offset], blob[offset + 1])
            flags = blob[offset + 2]
            macro.steps.append(
                MacroStep(
                    kind=flags & 0x3F,
                    code=blob[offset + 3],
                    press=bool(flags & STEP_FLAG_PRESS),
                    delay=delay,
                )
            )
            offset += MACRO_STEP_SIZE
            if flags & STEP_FLAG_LAST or flags == 0:
                break
    return macros


def encode_macros(macros: Iterable[Macro]) -> bytes:
    """Build a full 4096-byte macro area from a set of slots.

    The whole area is rewritten every time, because the step lists are packed
    and a slot changing length moves every slot after it. The index starts as
    all-0xFF, which is what the vendor writes for "no macro here".
    """
    blob = bytearray(b"\xff" * MACRO_INDEX_SIZE + b"\x00" * (MACRO_AREA_SIZE - MACRO_INDEX_SIZE))
    cursor = MACRO_INDEX_SIZE
    for macro in macros:
        if not 0 <= macro.slot < MACRO_SLOTS:
            raise SdcxError(f"macro slot {macro.slot} is out of range 0-{MACRO_SLOTS - 1}")
        if not macro.steps:
            continue
        needed = MACRO_STEP_SIZE * len(macro.steps)
        if cursor + needed > MACRO_AREA_SIZE:
            raise SdcxError(
                "the macros do not fit: the device has "
                f"{MACRO_AREA_SIZE - MACRO_INDEX_SIZE} bytes for steps, which is "
                f"{(MACRO_AREA_SIZE - MACRO_INDEX_SIZE) // MACRO_STEP_SIZE} steps in total"
            )
        blob[2 * macro.slot : 2 * macro.slot + 2] = bytes(u16le(cursor))
        for position, step in enumerate(macro.steps):
            last = position == len(macro.steps) - 1
            blob[cursor : cursor + MACRO_STEP_SIZE] = bytes(step.to_wire(last))
            cursor += MACRO_STEP_SIZE
    return bytes(blob)


# HID usages for the eight modifiers, in the bit order of the type-32 modifier
# mask. A macro has no modifier field, so a combination has to be spelled out as
# real press and release events.
_MODIFIER_USAGES = (224, 225, 226, 227, 228, 229, 230, 231)


def macro_from_sequence(text: str, delay: int = 10) -> list[MacroStep]:
    """Build a macro from a comma-separated list of keystrokes.

    "ctrl+c, a, enter" becomes press-ctrl, press-c, release-c, release-ctrl,
    press-a, release-a, and so on, with `delay` milliseconds between events.
    This covers what people actually want a keypad macro for; anything with
    per-step timing or held keys wants the JSON form instead.
    """
    steps: list[MacroStep] = []
    for token in (t.strip() for t in text.split(",")):
        if not token:
            continue
        code = parse_keycode(token)
        if code.type not in (32, 16):
            raise SdcxError(
                f"{token!r} is a {code.category} keycode; a macro sequence can only "
                "contain keyboard keys and mouse buttons"
            )
        if code.type == 16:
            steps.append(MacroStep(STEP_MOUSE, code.value1, True, delay))
            steps.append(MacroStep(STEP_MOUSE, code.value1, False, delay))
            continue
        modifiers = [u for bit, u in enumerate(_MODIFIER_USAGES) if code.value1 & (1 << bit)]
        for usage in modifiers:
            steps.append(MacroStep(STEP_KEYBOARD, usage, True, delay))
        steps.append(MacroStep(STEP_KEYBOARD, code.value2, True, delay))
        steps.append(MacroStep(STEP_KEYBOARD, code.value2, False, delay))
        for usage in reversed(modifiers):
            steps.append(MacroStep(STEP_KEYBOARD, usage, False, delay))
    if not steps:
        raise SdcxError("the macro sequence is empty")
    return steps


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

    # -- keymap ------------------------------------------------------------

    def _keymap_span(self) -> int:
        """Bytes of keymap that cover every addressable key on this device.

        Key indices are sparse (the K006's knob lives at 16-18 while its keys
        are 0-5) and the table is flat, four bytes per index. So the span to
        read is (highest index + 1) * 4, not (key count) * 4.
        """
        keys = self.layout.keys
        if not keys:
            raise SdcxError(
                "this device's key layout is not known to the driver, so the keymap "
                "cannot be addressed. Check the model with: sdcx list"
            )
        return (max(k.index for k in keys) + 1) * 4

    def get_keymap(self, layer: int = 0) -> dict[int, KeyAssignment]:
        """Read what every addressable key is currently bound to.

        Note the vendor app indexes its read result by the key's position in its
        own key list while writing by key_index; on a pad with sparse indices
        those disagree. This follows key_index for both, which is what the
        single-key write command (and the per-key colour table) uses.
        """
        span = self._keymap_span()
        data = bytearray()
        offset = 0
        while len(data) < span:
            resp = self._request([CMD_GET_KEYMAP, 58, *u16le(offset), 0, layer])
            data.extend(resp[8:64])
            offset += READ_CHUNK
        return {
            k.index: KeyAssignment(k.index, *data[4 * k.index : 4 * k.index + 4])
            for k in self.layout.keys
            if 4 * k.index + 3 < len(data)
        }

    def set_key(self, key_index: int, keycode: Keycode | str, layer: int = 0) -> KeyAssignment:
        """Rebind one key in a single transfer, with no read-modify-write.

        `keycode` may be anything parse_keycode() accepts, so callers can pass
        "ctrl+c" straight through.
        """
        code = parse_keycode(keycode) if isinstance(keycode, str) else keycode
        if self.layout.keys and self.layout.key_by_index(key_index) is None:
            valid = ", ".join(str(k.index) for k in self.layout.keys)
            raise SdcxError(f"key index {key_index} not on this device. Valid: {valid}")
        self._send(
            [
                CMD_SET_KEY_SINGLE,
                7,
                *u16le(key_index * 4),
                0,
                layer,
                0,
                *code.wire,
            ]
        )
        return KeyAssignment.from_keycode(key_index, code)

    def set_keymap(self, assignments: dict[int, KeyAssignment], layer: int = 0) -> None:
        """Write several keys at once, as bulk chunks.

        The table is flat and addressed by key_index, so a sparse update still
        has to send every byte up to the highest index it touches. Keys absent
        from `assignments` keep what the device already had, which is why this
        reads the current keymap first.
        """
        if not assignments:
            return
        current = self.get_keymap(layer)
        current.update(assignments)
        table = bytearray(self._keymap_span())
        for index, assignment in current.items():
            table[4 * index : 4 * index + 4] = bytes(assignment.wire)

        total = len(table)
        sent = 0
        chunk_index = 0
        while sent < total:
            chunk = table[sent : sent + READ_CHUNK]
            # Wire byte 1 is a length field the firmware reads as "data + 3".
            # A full chunk is 59; only the short final chunk states its own size.
            header_len = 59
            if sent + len(chunk) >= total and total % READ_CHUNK > 0:
                header_len = total % READ_CHUNK + 3
            self._send(
                [
                    CMD_SET_KEYMAP_BULK,
                    header_len,
                    *u16le(READ_CHUNK * chunk_index),
                    0,
                    layer,
                    *chunk,
                ]
            )
            sent += len(chunk)
            chunk_index += 1

    def get_key_infos(self) -> list[KeyAssignment]:
        """Read the firmware's own key table: what each key does as shipped.

        This is the 576-byte factory table behind `[7]`, not the per-layer user
        keymap. It is what `sdcx keymap reset` restores from.
        """
        data = bytearray()
        offset = 0
        while offset < 576:
            resp = self._request([CMD_GET_KEY_INFOS, 56, *u16le(offset)])
            data.extend(resp[8:64])
            offset += READ_CHUNK
        return [
            KeyAssignment(k.index, *data[4 * k.index : 4 * k.index + 4])
            for k in self.layout.keys
            if 4 * k.index + 3 < len(data)
        ]

    def reset_keymap(self, layer: int = 0) -> dict[int, KeyAssignment]:
        """Put every key back to the function the firmware ships it with.

        There is no "reset keymap" command; `[15, 255]` resets everything
        including the colours and macros. So this reads the factory key table
        and writes it back over the layer, which touches nothing else.
        """
        defaults = {a.key_index: a for a in self.get_key_infos()}
        if not defaults:
            raise SdcxError("the device returned no factory key table to restore from")
        self.set_keymap(defaults, layer)
        return defaults

    # -- macros ------------------------------------------------------------

    def get_macro_data(self) -> bytes:
        """Read the whole 4096-byte macro area."""
        data = bytearray()
        offset = 0
        while offset < MACRO_AREA_SIZE:
            length = min(MACRO_AREA_SIZE - offset, READ_CHUNK)
            resp = self._request([CMD_GET_MACRO, length, *u16le(offset)])
            data.extend(resp[8 : 8 + length])
            offset += READ_CHUNK
        return bytes(data[:MACRO_AREA_SIZE])

    def set_macro_data(self, blob: bytes) -> None:
        """Write the macro area back.

        Writes chunk at 59 bytes, not the 56 reads use: the write frame spends
        only four bytes on its header, so three more data bytes fit. Each chunk
        declares its own length in wire byte 1.
        """
        if len(blob) > MACRO_AREA_SIZE:
            raise SdcxError(
                f"macro data is {len(blob)} bytes; the device has {MACRO_AREA_SIZE}"
            )
        for offset in range(0, len(blob), MACRO_WRITE_CHUNK):
            chunk = blob[offset : offset + MACRO_WRITE_CHUNK]
            self._send([CMD_SET_MACRO, len(chunk), *u16le(offset), *chunk])

    def get_macros(self) -> list[Macro]:
        return decode_macros(self.get_macro_data())

    def set_macros(self, macros: Iterable[Macro]) -> None:
        """Replace every macro slot. Slots not listed are left empty."""
        self.set_macro_data(encode_macros(macros))

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
