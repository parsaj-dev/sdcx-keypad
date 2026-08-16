"""The keycode tables, and the parser that turns human text into wire bytes.

A keymap entry is four bytes: `[type, value1, value2, value3]`. `type` selects
which of the device's several input engines runs, and the three values mean
different things in each. The tables below were extracted programmatically from
the vendor bundle (`.vendor-bundle/.../page-*.js`) rather than transcribed, so
they are exactly what the vendor web app writes.

The `type` values, and what the firmware does with them:

| type | engine | value1 | value2 | value3 |
|---|---|---|---|---|
| 16 | mouse button / wheel | button bitmask | – | wheel delta, signed 8-bit |
| 17 | mouse cursor move | – | – | – |
| 19 | key disabled (DISKEY) | – | – | – |
| 31 | on-device control | function id (see `_CONTROL`) | – | – |
| 32 | standard keyboard | modifier bitmask | HID usage code | – |
| 48 | consumer / multimedia | usage low byte | usage high byte | – |
| 64 | system control | 1 power, 2 sleep, 4 wake | – | – |
| 96 | run a macro | macro slot 0-15 | repeat mode (1 = once) | – |
| 128 | open a website | – | – | – |
| 255 | custom combination | – | – | – |

Types 128 and 255 are stored in areas this driver does not write (the URL blob
and the vendor's combination editor), so they are decodable but not settable.

The type-32 modifier bitmask is the standard HID one, and the bundle's decoder
confirms the bit order:

    bit 0 LCTRL   bit 1 LSHIFT   bit 2 LALT   bit 3 LWIN
    bit 4 RCTRL   bit 5 RSHIFT   bit 6 RALT   bit 7 RWIN
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .device import SdcxError

# Type selectors. Named after the vendor's own enum where it has one
# (MouseMove = 17, Standard = 32, OpenWebsite = 128, CustomCombination = 255).
TYPE_MOUSE = 16
TYPE_MOUSE_MOVE = 17
TYPE_DISABLED = 19
TYPE_CONTROL = 31
TYPE_STANDARD = 32
TYPE_CONSUMER = 48
TYPE_SYSTEM = 64
TYPE_MACRO = 96
TYPE_OPEN_WEBSITE = 128
TYPE_CUSTOM_COMBINATION = 255

TYPE_NAMES: dict[int, str] = {
    TYPE_MOUSE: "mouse",
    TYPE_MOUSE_MOVE: "mouse-move",
    TYPE_DISABLED: "disabled",
    TYPE_CONTROL: "control",
    TYPE_STANDARD: "keyboard",
    TYPE_CONSUMER: "consumer",
    TYPE_SYSTEM: "system",
    TYPE_MACRO: "macro",
    TYPE_OPEN_WEBSITE: "website",
    TYPE_CUSTOM_COMBINATION: "combination",
}

MODIFIER_BITS: dict[str, int] = {
    "lctrl": 0x01,
    "lshift": 0x02,
    "lalt": 0x04,
    "lwin": 0x08,
    "rctrl": 0x10,
    "rshift": 0x20,
    "ralt": 0x40,
    "rwin": 0x80,
}

# The names a person actually types. Everything resolves to a left-hand
# modifier, which is what the vendor UI emits for an unqualified "ctrl".
MODIFIER_ALIASES: dict[str, str] = {
    "ctrl": "lctrl",
    "control": "lctrl",
    "ctl": "lctrl",
    "shift": "lshift",
    "alt": "lalt",
    "opt": "lalt",
    "option": "lalt",
    "win": "lwin",
    "super": "lwin",
    "meta": "lwin",
    "gui": "lwin",
    "cmd": "lwin",
    "command": "lwin",
    "lctrl": "lctrl",
    "lshift": "lshift",
    "lalt": "lalt",
    "lwin": "lwin",
    "rctrl": "rctrl",
    "rshift": "rshift",
    "ralt": "ralt",
    "altgr": "ralt",
    "rwin": "rwin",
}

MAX_MACRO_SLOTS = 16


@dataclass(frozen=True)
class Keycode:
    """One nameable assignment, as four wire bytes plus a human name."""

    name: str
    code: str
    type: int
    value1: int
    value2: int
    value3: int
    category: str

    @property
    def wire(self) -> tuple[int, int, int, int]:
        return (self.type, self.value1, self.value2, self.value3)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "code": self.code,
            "category": self.category,
            "type": self.type,
            "type_name": TYPE_NAMES.get(self.type, str(self.type)),
            "wire": list(self.wire),
        }


# -- source tables ---------------------------------------------------------
#
# Keyboard usages come from the bundle's `b` map (DOM `KeyboardEvent.code` ->
# HID usage), not from its "Basic" keycode category: that category's names are
# UI captions carrying embedded newlines ("!\n1") and blanks, which are useless
# as things to type on a command line.

_KEYBOARD: tuple[tuple[str, int], ...] = (
    ("1", 30), ("2", 31), ("3", 32), ("4", 33), ("5", 34),
    ("6", 35), ("7", 36), ("8", 37), ("9", 38), ("0", 39),
    ("a", 4), ("b", 5), ("c", 6), ("d", 7), ("e", 8), ("f", 9),
    ("g", 10), ("h", 11), ("i", 12), ("j", 13), ("k", 14), ("l", 15),
    ("m", 16), ("n", 17), ("o", 18), ("p", 19), ("q", 20), ("r", 21),
    ("s", 22), ("t", 23), ("u", 24), ("v", 25), ("w", 26), ("x", 27),
    ("y", 28), ("z", 29),
    ("comma", 54), ("period", 55), ("semicolon", 51), ("quote", 52),
    ("bracket_left", 47), ("bracket_right", 48), ("backspace", 42),
    ("backquote", 53), ("slash", 56), ("backslash", 49), ("minus", 45),
    ("equal", 46), ("intl_ro", 135), ("intl_yen", 137),
    ("alt_left", 226), ("alt_right", 230), ("caps_lock", 57),
    ("control_left", 224), ("control_right", 228),
    ("meta_left", 227), ("meta_right", 231),
    ("shift_left", 225), ("shift_right", 229),
    ("context_menu", 101), ("enter", 40), ("space", 44), ("tab", 43),
    ("delete", 76), ("end", 77), ("help", 117), ("home", 74), ("insert", 73),
    ("page_down", 78), ("page_up", 75),
    ("down", 81), ("left", 80), ("right", 79), ("up", 82),
    ("escape", 41), ("print_screen", 70), ("scroll_lock", 71),
    # These three are the keyboard page's own volume usages, distinct from the
    # consumer-page ones below; most hosts honour the consumer ones instead.
    ("audio_volume_up", 169), ("audio_volume_down", 170),
    ("audio_volume_mute", 168),
    ("pause", 72),
    ("f1", 58), ("f2", 59), ("f3", 60), ("f4", 61), ("f5", 62), ("f6", 63),
    ("f7", 64), ("f8", 65), ("f9", 66), ("f10", 67), ("f11", 68), ("f12", 69),
    ("f13", 104), ("f14", 105), ("f15", 106), ("f16", 107), ("f17", 108),
    ("f18", 109), ("f19", 110), ("f20", 111), ("f21", 112), ("f22", 113),
    ("f23", 114), ("f24", 115),
    ("num_lock", 83),
    ("kp_0", 98), ("kp_1", 89), ("kp_2", 90), ("kp_3", 91), ("kp_4", 92),
    ("kp_5", 93), ("kp_6", 94), ("kp_7", 95), ("kp_8", 96), ("kp_9", 97),
    ("kp_add", 87), ("kp_comma", 54), ("kp_decimal", 99), ("kp_divide", 84),
    ("kp_enter", 88), ("kp_equal", 103), ("kp_multiply", 85),
    ("kp_subtract", 86),
)

# Consumer-page usages, split little-endian across value1/value2.
_CONSUMER: tuple[tuple[str, int, int], ...] = (
    ("volume_up", 233, 0),
    ("volume_down", 234, 0),
    ("mute", 226, 0),
    ("play_pause", 205, 0),
    ("stop", 183, 0),
    ("prev_track", 182, 0),
    ("next_track", 181, 0),
    ("multimedia", 131, 1),
    ("homepage", 35, 2),
    ("web_refresh", 39, 2),
    ("web_stop", 38, 2),
    ("web_forward", 37, 2),
    ("web_backward", 36, 2),
    ("web_favorites", 42, 2),
    ("web_search", 33, 2),
    ("calculator", 146, 1),
    ("my_computer", 148, 1),
    ("mail", 138, 1),
    ("screen_brightness_down", 112, 0),
    ("screen_brightness_up", 111, 0),
)

# Mouse. value1 is a button bitmask; value3 is a signed wheel delta, so 255 is
# one click down rather than 255 clicks.
_MOUSE: tuple[tuple[str, int, int, int, int], ...] = (
    ("mouse_left", TYPE_MOUSE, 1, 0, 0),
    ("mouse_right", TYPE_MOUSE, 2, 0, 0),
    ("mouse_middle", TYPE_MOUSE, 4, 0, 0),
    ("mouse_backward", TYPE_MOUSE, 8, 0, 0),
    ("mouse_forward", TYPE_MOUSE, 16, 0, 0),
    ("wheel_up", TYPE_MOUSE, 0, 0, 1),
    ("wheel_down", TYPE_MOUSE, 0, 0, 255),
    ("cursor_move", TYPE_MOUSE_MOVE, 0, 0, 0),
)

# System-control page: a bitmask, not a usage.
_SYSTEM: tuple[tuple[str, int], ...] = (
    ("power", 1),
    ("sleep", 2),
    ("wakeup", 4),
)

# Type 31 is handled entirely on the device: the host never sees these. value1
# is a function selector. Note the vendor's own table gives "Light Effect" and
# "Brightness+" the same value1 (1); the firmware has one meaning for it, and
# from the surrounding ids (2 = Brightness-) it is the brightness one. Both
# names are kept so either resolves, but they are the same assignment.
_CONTROL: tuple[tuple[str, int], ...] = (
    ("light_switch", 0),
    ("brightness_up", 1),
    ("light_effect", 1),
    ("brightness_down", 2),
    ("color_switch", 4),
    ("speed_up", 5),
    ("speed_down", 6),
    ("profile_switch", 19),
    ("light_direction", 20),
    ("lock_keyboard", 25),
)


def _build_registry() -> tuple[Keycode, ...]:
    entries: list[Keycode] = [
        Keycode("disabled", "KC_DISKEY", TYPE_DISABLED, 0, 0, 0, "special"),
    ]
    entries += [
        Keycode(name, f"KC_{name.upper()}", TYPE_STANDARD, 0, usage, 0, "keyboard")
        for name, usage in _KEYBOARD
    ]
    entries += [
        Keycode(name, f"KC_{name.upper()}", TYPE_CONSUMER, lo, hi, 0, "media")
        for name, lo, hi in _CONSUMER
    ]
    entries += [
        Keycode(name, name.upper(), type_, v1, v2, v3, "mouse")
        for name, type_, v1, v2, v3 in _MOUSE
    ]
    entries += [
        Keycode(name, name.upper(), TYPE_SYSTEM, mask, 0, 0, "system")
        for name, mask in _SYSTEM
    ]
    entries += [
        Keycode(name, name.upper(), TYPE_CONTROL, func, 0, 0, "control")
        for name, func in _CONTROL
    ]
    # Macro slots are a fixed set rather than a parsed range so that `sdcx
    # keycodes` can list them; `macro:N` in parse_keycode() covers the rest.
    entries += [
        Keycode(f"macro:{n}", f"MACRO({n})", TYPE_MACRO, n, 1, 0, "macro")
        for n in range(MAX_MACRO_SLOTS)
    ]
    return tuple(entries)


REGISTRY: tuple[Keycode, ...] = _build_registry()

CATEGORIES: tuple[str, ...] = ("keyboard", "media", "mouse", "system", "control", "macro", "special")


def _normalise(text: str) -> str:
    """Fold the ways a person writes one name down to one lookup key.

    "Volume +", "volume_up", "VOLUME-UP" and "volume up" are the same request;
    the tables above are keyed on the folded form.
    """
    return re.sub(r"[\s_\-]+", "", text.strip().lower())


_BY_NAME: dict[str, Keycode] = {}
for _kc in REGISTRY:
    _BY_NAME.setdefault(_normalise(_kc.name), _kc)
    _BY_NAME.setdefault(_normalise(_kc.code), _kc)

# A handful of spellings people reach for that are not the canonical name.
_ALIASES: dict[str, str] = {
    "esc": "escape",
    "return": "enter",
    "del": "delete",
    "ins": "insert",
    "pgup": "page_up",
    "pgdn": "page_down",
    "pgdown": "page_down",
    "bksp": "backspace",
    "capslock": "caps_lock",
    "prtsc": "print_screen",
    "printscreen": "print_screen",
    "menu": "context_menu",
    "app": "context_menu",
    "volup": "volume_up",
    "voldown": "volume_down",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "none": "disabled",
    "off": "disabled",
    "diskey": "disabled",
    "grave": "backquote",
    "tilde": "backquote",
    "lbracket": "bracket_left",
    "rbracket": "bracket_right",
    "play": "play_pause",
    "pause_media": "play_pause",
}
for _alias, _target in _ALIASES.items():
    _BY_NAME.setdefault(_normalise(_alias), _BY_NAME[_normalise(_target)])


def lookup(name: str) -> Keycode | None:
    """Find one keycode by any of its spellings. Case- and separator-blind."""
    return _BY_NAME.get(_normalise(name))


def search(text: str) -> list[Keycode]:
    """Substring match over names and codes, for `sdcx keycodes --search`."""
    needle = _normalise(text)
    return [
        kc
        for kc in REGISTRY
        if needle in _normalise(kc.name) or needle in _normalise(kc.code)
    ]


def by_category(category: str) -> list[Keycode]:
    target = category.strip().lower()
    return [kc for kc in REGISTRY if kc.category == target]


def _split_combo(text: str) -> list[str]:
    """Split "ctrl+shift+a" / "Ctrl - A" / "ctrl-a" into its parts.

    "+" and "-" are separators, but they are also keys people bind, so a
    trailing one is put back as the final part: "ctrl++" is ctrl plus the plus
    key, not a malformed combination.
    """
    body = text.strip()
    trailing = body[-1] if body[-1:] in ("+", "-") else ""
    if trailing:
        body = body[:-1]
    parts = [p.strip() for p in re.split(r"\s*[+\-]\s*", body) if p.strip()]
    if trailing:
        parts.append("equal" if trailing == "+" else "minus")
    if not parts:
        raise SdcxError("empty keycode")
    return parts


def parse_keycode(text: str) -> Keycode:
    """Turn user input into the four bytes the firmware wants.

    Accepts a plain name ("f5", "volume_up", "light_switch"), a macro reference
    ("macro:3", "m3"), a raw four-byte spec ("raw:32,1,6,0") for anything the
    tables do not name, or a modifier combination ("ctrl+c", "Ctrl + Shift - S").

    Combinations are only expressible on type 32, because that is the only type
    with a modifier field; "ctrl+volume_up" is therefore refused rather than
    silently dropping the modifier.
    """
    raw = text.strip()
    if not raw:
        raise SdcxError("empty keycode")

    lowered = raw.lower()

    if lowered.startswith("raw:"):
        try:
            values = [int(v, 0) for v in lowered[4:].split(",")]
        except ValueError as exc:
            raise SdcxError(
                f"{raw!r} is not a raw keycode; expected raw:type,v1,v2,v3"
            ) from exc
        if len(values) != 4 or any(not 0 <= v <= 255 for v in values):
            raise SdcxError(
                f"{raw!r} is not a raw keycode; expected four bytes 0-255, "
                "e.g. raw:32,1,6,0"
            )
        return Keycode("raw", raw, *values, category="raw")

    macro = re.fullmatch(r"(?:macro:?|m)\s*(\d+)", lowered)
    if macro:
        slot = int(macro.group(1))
        if slot >= MAX_MACRO_SLOTS:
            raise SdcxError(
                f"macro slot {slot} does not exist; the device has "
                f"{MAX_MACRO_SLOTS} slots (0-{MAX_MACRO_SLOTS - 1})"
            )
        return Keycode(f"macro:{slot}", f"MACRO({slot})", TYPE_MACRO, slot, 1, 0, "macro")

    direct = lookup(raw)
    if direct is not None:
        return direct

    parts = _split_combo(raw)
    if len(parts) == 1 and "_" in raw:
        # Underscore is part of a name ("volume_up"), not a separator — except
        # in the vendor's own shortcut spelling, "CTRL_C". Only treat it as one
        # when the leading token is a modifier and the whole thing named nothing.
        head, _, tail = raw.partition("_")
        if _normalise(head) in MODIFIER_ALIASES and tail:
            parts = [head, tail]
    if len(parts) == 1:
        raise SdcxError(
            f"unknown keycode {parts[0]!r}. "
            "List what is available with: sdcx keycodes --search " + parts[0]
        )

    # The last part is the key; everything before it must be a modifier. That
    # ordering is what people write, and it keeps "ctrl+shift" (all modifiers)
    # from silently resolving to something.
    *modifier_parts, key_part = parts
    mask = 0
    names: list[str] = []
    for part in modifier_parts:
        modifier = MODIFIER_ALIASES.get(_normalise(part))
        if modifier is None:
            raise SdcxError(
                f"{part!r} in {raw!r} is not a modifier. Modifiers are: "
                + ", ".join(sorted(set(MODIFIER_ALIASES)))
            )
        mask |= MODIFIER_BITS[modifier]
        names.append(modifier)

    base = lookup(key_part)
    if base is None:
        if _normalise(key_part) in MODIFIER_ALIASES:
            raise SdcxError(
                f"{raw!r} is only modifiers. To bind a modifier by itself use its "
                "key name, e.g. control_left or shift_right"
            )
        raise SdcxError(
            f"unknown key {key_part!r} in {raw!r}. "
            "List what is available with: sdcx keycodes --search " + key_part
        )
    if base.type != TYPE_STANDARD:
        raise SdcxError(
            f"{base.name} is a {TYPE_NAMES.get(base.type, base.type)} keycode and "
            "cannot carry modifiers; only standard keyboard keys can"
        )

    return Keycode(
        name="+".join(names + [base.name]),
        code=base.code,
        type=TYPE_STANDARD,
        value1=mask,
        value2=base.value2,
        value3=base.value3,
        category="combo",
    )


def describe(type_: int, value1: int, value2: int, value3: int) -> str:
    """Render four wire bytes as the name a person would type back in.

    Reverses parse_keycode() where it can. An assignment the tables do not name
    comes back as its raw spec rather than as an empty string, so a round-trip
    through `sdcx keymap get` never loses information.
    """
    if type_ == 0 and value1 == 0 and value2 == 0 and value3 == 0:
        return "unset"
    if type_ == TYPE_MACRO:
        return f"macro:{value1}"
    if type_ == TYPE_STANDARD:
        base = next(
            (kc for kc in REGISTRY if kc.type == TYPE_STANDARD and kc.value2 == value2),
            None,
        )
        label = base.name if base else f"usage {value2}"
        if value1:
            mods = [n for n, bit in MODIFIER_BITS.items() if value1 & bit]
            return "+".join(mods + [label])
        return label
    exact = next((kc for kc in REGISTRY if kc.wire == (type_, value1, value2, value3)), None)
    if exact is not None:
        return exact.name
    return f"raw:{type_},{value1},{value2},{value3}"
