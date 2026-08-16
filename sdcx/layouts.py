"""Per-device capability descriptions.

The vendor web app ships one JSON per USB ID describing the light modes the
firmware implements and where the physical keys sit. The parts a driver needs,
which modes exist and which key indices are addressable, are transcribed here
so the package has no runtime dependency on the vendor's site.

devices.json, shipped inside this package, holds the full 196-ID list the
vendor bundle accepts. Only devices with an entry in LAYOUTS below have a verified key map;
everything else falls back to a generic profile that still supports the global
lighting commands, which are identical across the family.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_DEVICE_LIST = Path(__file__).resolve().parent / "devices.json"


@dataclass(frozen=True)
class LightMode:
    value: int
    name: str
    name_zh: str
    brightness: bool = False
    speed: bool = False
    direction: bool = False
    color: bool = False
    palette: bool = False


@dataclass(frozen=True)
class Key:
    """One addressable input.

    `index` is the device's key_index, used to address the key in per-key colour
    and keymap writes. It is sparse: on the K006 the six keys are 0-5 but the
    three knob actions are 16, 17 and 18.

    `row`/`col` are the key's position as it physically sits on the pad, derived
    from the x/y coordinates in the vendor layout. They are deliberately not the
    JSON's own `row`/`col`, which are electrical matrix positions and do not
    correspond to where the key is on the board; a UI drawing the pad wants the
    physical arrangement.
    """

    index: int
    label: str
    row: int
    col: int
    kind: str = "key"  # "key" | "knob"


@dataclass(frozen=True)
class Layout:
    model: str
    vendor_id: int
    product_id: int
    keys: tuple[Key, ...]
    modes: tuple[LightMode, ...]
    matrix_rows: int = 0
    matrix_cols: int = 0
    mcu_type: str = ""
    verified: bool = False

    @property
    def key_count(self) -> int:
        return len(self.keys)

    def mode_by_value(self, value: int) -> LightMode | None:
        return next((m for m in self.modes if m.value == value), None)

    def mode_by_name(self, name: str) -> LightMode | None:
        target = name.strip().lower().replace("-", " ").replace("_", " ")
        return next(
            (m for m in self.modes if m.name.lower().replace("-", " ") == target), None
        )

    def key_by_index(self, index: int) -> Key | None:
        return next((k for k in self.keys if k.index == index), None)


# Modes as declared in 0816_246f.json. The booleans mirror the vendor's own
# capability flags: they say which fields the firmware honours in that mode.
_K006_MODES = (
    LightMode(0, "Off", "关闭"),
    LightMode(1, "Steady", "常亮", brightness=True, color=True, palette=True),
    LightMode(2, "Breath", "呼吸", brightness=True, speed=True, color=True, palette=True),
    LightMode(3, "Press-lit", "按亮", brightness=True, speed=True, color=True, palette=True),
    LightMode(4, "Tidal", "潮汐", brightness=True, speed=True, color=True, palette=True),
    LightMode(5, "Custom", "custom", brightness=True, palette=True),
)

_K006 = Layout(
    model="HCY-K006",
    vendor_id=0x0816,
    product_id=0x246F,
    matrix_rows=6,
    matrix_cols=5,
    mcu_type="951",
    verified=True,
    modes=_K006_MODES,
    keys=(
        # Two visual rows of three, from the x/y coordinates in 0816_246f.json:
        # indices 0-2 sit at y=1.05, indices 3-5 at y=3.1.
        Key(0, "Key 1", 0, 0),
        Key(1, "Key 2", 0, 1),
        Key(2, "Key 3", 0, 2),
        Key(3, "Key 4", 1, 0),
        Key(4, "Key 5", 1, 1),
        Key(5, "Key 6", 1, 2),
        # The knob's three actions. They share one physical encoder, so a UI
        # should draw them as one control rather than as three keys.
        #
        # Rotation direction is taken from what the firmware actually ships:
        # reading the factory keymap gives index 17 = volume up, 18 = volume
        # down, and louder-clockwise is universal. The vendor's own layout JSON
        # captions them the other way round (18 = 音量+), which contradicts both
        # its firmware and the x-coordinates it gives them; it is wrong.
        Key(17, "Knob CW", 0, 3, kind="knob"),
        Key(16, "Knob press", 1, 3, kind="knob"),
        Key(18, "Knob CCW", 2, 3, kind="knob"),
    ),
)

LAYOUTS: dict[tuple[int, int], Layout] = {
    (_K006.vendor_id, _K006.product_id): _K006,
}


def generic_layout(vendor_id: int, product_id: int) -> Layout:
    """Fallback for a supported USB ID with no transcribed key map.

    Global lighting works identically across the family, so this exposes the
    standard mode set and no keys. Per-key operations will report that the
    layout is unknown rather than guessing at indices.
    """
    return Layout(
        model=f"Unknown ({vendor_id:04x}:{product_id:04x})",
        vendor_id=vendor_id,
        product_id=product_id,
        keys=(),
        modes=_K006_MODES,
        verified=False,
    )


def get_layout(vendor_id: int, product_id: int) -> Layout:
    return LAYOUTS.get((vendor_id, product_id)) or generic_layout(vendor_id, product_id)


def _load_supported() -> set[tuple[int, int]]:
    try:
        raw = json.loads(_DEVICE_LIST.read_text())
    except (OSError, ValueError):
        return set(LAYOUTS)
    return {
        (int(d["vendor_id"], 16), int(d["product_id"], 16)) for d in raw.get("devices", [])
    }


_SUPPORTED: set[tuple[int, int]] = _load_supported()


def is_supported(vendor_id: int, product_id: int) -> bool:
    return (vendor_id, product_id) in _SUPPORTED


def supported_ids() -> list[tuple[int, int]]:
    return sorted(_SUPPORTED)
