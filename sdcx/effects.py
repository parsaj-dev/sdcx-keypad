"""Host-driven lighting effects.

The firmware's own effects (light modes 0-4) run on the keypad and know nothing
about the machine they are plugged into. These run on the host instead: each
frame is computed here and pushed as per-key colours, which is what makes
something like a CPU heat map possible at all.

Two hardware facts shape everything below:

* Per-key colour is only visible in light mode 5 (Custom). In any other mode the
  on-device effect engine repaints the LEDs and the writes appear to do nothing,
  so every run switches to mode 5 first.
* Each `set_key_color` is one 64-byte interrupt transfer on a full-speed bus.
  Nine keys at 20fps is 180 transfers/second, which the device handles happily;
  the render loop caps fps at MAX_FPS so a stray `--fps 500` cannot saturate it.

Effects are parameterised declaratively: each one names the parameters it
accepts out of PARAM_LIBRARY, and that single declaration drives three things at
once — the argparse flags, the JSON manifest a GUI builds its controls from, and
the values handed to the render function. Adding a knob to an effect is one name
in one tuple; nothing else has to learn about it.

See docs/PROTOCOL.md §3 for the underlying commands.
"""

from __future__ import annotations

import argparse
import colorsys
import glob
import json
import math
import os
import random
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .device import SdcxError
from .layouts import Key
from .protocol import Keypad, parse_hex_color

CUSTOM_MODE = 5

# Above this the transfers stop being visible as separate frames and only cost
# bus bandwidth; the LEDs themselves are nowhere near this responsive.
MAX_FPS = 60.0

Rgb = tuple[int, int, int]
Frame = dict[int, Rgb]


# -- the parameter schema --------------------------------------------------


@dataclass(frozen=True)
class EffectParam:
    """One knob an effect exposes.

    `kind` is what a UI needs to pick a widget: "color" is a swatch, "float" and
    "int" are sliders bounded by minimum/maximum, "bool" is a checkbox, "choice"
    is a menu over `choices`. `default` is always a value the render function can
    use directly, so an effect run with no flags at all is still well defined.
    """

    name: str
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    description: str = ""

    @property
    def flag(self) -> str:
        """The CLI spelling: underscores become dashes, as argparse conventions go."""
        return "--" + self.name.replace("_", "-")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "flag": self.flag,
            "kind": self.kind,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "choices": list(self.choices) if self.choices else None,
            "description": self.description,
        }

    def coerce(self, value: Any) -> Any:
        """Turn a CLI string or a GUI's JSON value into what the renderer wants.

        Out-of-range numbers clamp rather than raise: a slider dragged to the end
        of its track should behave, and the alternative is an effect that dies
        three frames in because someone typed --speed 1000.
        """
        if value is None:
            return self.default
        if self.kind == "color":
            return parse_hex_color(value) if isinstance(value, str) else tuple(value)
        if self.kind == "bool":
            return bool(value)
        if self.kind == "choice":
            text = str(value)
            if self.choices and text not in self.choices:
                raise SdcxError(
                    f"{self.flag}: {text!r} is not one of {', '.join(self.choices)}"
                )
            return text
        try:
            number = float(value) if self.kind == "float" else int(value)
        except (TypeError, ValueError) as exc:
            raise SdcxError(f"{self.flag}: {value!r} is not a {self.kind}") from exc
        if self.minimum is not None:
            number = max(number, type(number)(self.minimum))
        if self.maximum is not None:
            number = min(number, type(number)(self.maximum))
        return number


# Parameters are defined once, globally, and shared by name. Two effects that
# both take a "speed" must mean the same thing by it and get the same flag with
# the same range, otherwise the union of flags that register_effect_arguments
# builds would be ambiguous.
PARAM_LIBRARY: dict[str, EffectParam] = {
    "color": EffectParam(
        "color", "color", "#7c4dff",
        description="primary colour",
    ),
    "secondary_color": EffectParam(
        "secondary_color", "color", "#00e5ff",
        description="second colour, for gradients and two-tone effects",
    ),
    "speed": EffectParam(
        "speed", "float", 1.0, 0.05, 20.0,
        description="animation rate multiplier; 1.0 is the effect's natural pace",
    ),
    "intensity": EffectParam(
        "intensity", "float", 1.0, 0.0, 1.0,
        description="overall brightness ceiling",
    ),
    "reverse": EffectParam(
        "reverse", "bool", False,
        description="run the motion the other way along the pad",
    ),
    "palette": EffectParam(
        "palette", "choice", "custom",
        choices=("custom", "rainbow", "fire", "ice", "mono"),
        description=(
            "colour ramp: 'custom' interpolates primary to secondary, the rest "
            "are fixed ramps that ignore both colours"
        ),
    ),
    "duty": EffectParam(
        "duty", "float", 0.5, 0.02, 0.98,
        description="fraction of each cycle spent lit",
    ),
    "density": EffectParam(
        "density", "float", 0.25, 0.0, 1.0,
        description="how often a new key lights per second, per key",
    ),
    "decay": EffectParam(
        "decay", "float", 0.5, 0.05, 5.0,
        description="how fast a lit key fades, in units of brightness per second",
    ),
    "origin": EffectParam(
        "origin", "int", 4, 0, 8,
        description="key to radiate from, as a position in the main-key order",
    ),
    "smoothing": EffectParam(
        "smoothing", "float", 0.7, 0.0, 0.99,
        description=(
            "how much of the previous reading a meter keeps; higher is calmer "
            "and slower to react"
        ),
    ),
    "field": EffectParam(
        "field", "choice", "cycle",
        choices=("cycle", "hour", "minute", "second"),
        description="which part of the time to show, or cycle through all three",
    ),
    "dwell": EffectParam(
        "dwell", "float", 2.0, 0.5, 30.0,
        description="seconds each field is displayed before the next one",
    ),
    "low": EffectParam(
        "low", "float", 35.0, -50.0, 200.0,
        description="reading mapped to the cold end of the ramp",
    ),
    "high": EffectParam(
        "high", "float", 85.0, -50.0, 200.0,
        description="reading mapped to the hot end of the ramp",
    ),
    "seed": EffectParam(
        "seed", "int", 0, 0, 2**31 - 1,
        description=(
            "seed for randomised effects; the same seed and fps replays the same "
            "frames exactly, which is what makes them testable"
        ),
    ),
}


def _params(*names: str) -> tuple[EffectParam, ...]:
    return tuple(PARAM_LIBRARY[name] for name in names)


@dataclass
class EffectParams:
    """Everything a render function is allowed to depend on besides time.

    `values` holds the resolved parameters, already coerced and defaulted, keyed
    by the schema name. `state` is per-run mutable scratch, owned by the effect:
    it exists for effects that are not pure functions of the clock — `cpu` keeps
    its previous /proc/stat sample there. Nothing here is global, so two effects
    running in two processes cannot interfere.
    """

    color: Rgb = (0x7C, 0x4D, 0xFF)
    fps: float = 20.0
    values: dict[str, Any] = field(default_factory=dict)
    state: dict = field(default_factory=dict)

    def get(self, name: str) -> Any:
        """Resolved value, falling back to the library default if unset.

        The fallback matters because render functions are also called directly
        from tests and from the GUI's preview path, where nobody has been through
        argparse and `values` may be empty.
        """
        if name in self.values:
            return self.values[name]
        param = PARAM_LIBRARY.get(name)
        if param is None:
            raise SdcxError(f"no such effect parameter: {name!r}")
        return param.coerce(None)

    def flt(self, name: str) -> float:
        return float(self.get(name))

    def rgb(self, name: str) -> Rgb:
        value = self.get(name)
        return parse_hex_color(value) if isinstance(value, str) else tuple(value)  # type: ignore[return-value]


RenderFn = Callable[[int, float, tuple[Key, ...], EffectParams], Frame]
ProbeFn = Callable[[], None]


@dataclass(frozen=True)
class Effect:
    name: str
    description: str
    render: RenderFn
    help: str = ""
    params: tuple[EffectParam, ...] = ()
    # Called once before the device is opened. Effects backed by /proc or /sys
    # use it to fail loudly at startup on a machine that does not have the file,
    # rather than throwing out of the render loop with the pad mid-frame.
    probe: ProbeFn | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "help": self.help or self.description,
            "params": [p.to_dict() for p in self.params],
        }


# -- colour helpers --------------------------------------------------------


def _hsv(h: float, s: float, v: float) -> Rgb:
    """h wraps, s and v clamp. All 0-1."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return round(r * 255), round(g * 255), round(b * 255)


def _scale(rgb: Rgb, factor: float) -> Rgb:
    factor = max(0.0, min(1.0, factor))
    return round(rgb[0] * factor), round(rgb[1] * factor), round(rgb[2] * factor)


def _mix(a: Rgb, b: Rgb, t: float) -> Rgb:
    """Linear blend in RGB. Not perceptually even, but it is what the LEDs do."""
    t = max(0.0, min(1.0, t))
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def _ramp(t: float, params: EffectParams) -> Rgb:
    """Colour at position t (0-1) along whichever ramp `palette` selects."""
    t = max(0.0, min(1.0, t))
    palette = params.get("palette")
    if palette == "rainbow":
        return _hsv(t, 1.0, 1.0)
    if palette == "fire":
        # Black through red and orange to white: the classic heat ramp, which
        # reads as temperature even when the pad is the only light in the room.
        if t < 0.5:
            return _mix((0, 0, 0), (255, 40, 0), t * 2.0)
        return _mix((255, 40, 0), (255, 230, 160), (t - 0.5) * 2.0)
    if palette == "ice":
        return _mix((0, 12, 60), (190, 245, 255), t)
    if palette == "mono":
        return _scale(params.rgb("color"), t)
    return _mix(params.rgb("color"), params.rgb("secondary_color"), t)


def _main_keys(keys: tuple[Key, ...]) -> tuple[Key, ...]:
    """The six switches, in label order; knobs are separate on the K006."""
    return tuple(k for k in keys if k.kind == "key")


def _ordered(keys: tuple[Key, ...]) -> tuple[Key, ...]:
    """Every key as one strip: the switches first, then the knob actions.

    Bar-style effects want a single well-defined order over all nine LEDs, and
    key index is not it — the indices are sparse (0-5 then 16-18) and the knob
    actions are numbered 18, 16, 17 in physical top-to-bottom order.
    """
    return _main_keys(keys) + tuple(sorted(
        (k for k in keys if k.kind != "key"), key=lambda k: (k.row, k.col)
    ))


def _position(key: Key, keys: tuple[Key, ...], reverse: bool) -> float:
    """Where a key sits along the pad's diagonal, 0-1.

    Spatial phase comes from the physical position rather than the key index for
    the same reason as above: the index is sparse and would leave a gap in any
    sweep across the board.
    """
    span = max(1, max(k.row + k.col for k in keys))
    t = (key.row + key.col) / span
    return 1.0 - t if reverse else t


def _dark(keys: tuple[Key, ...]) -> Frame:
    return {k.index: (0, 0, 0) for k in keys}


def _bar(keys: tuple[Key, ...], fraction: float, params: EffectParams) -> Frame:
    """Light the first `fraction` of the strip, coloured by position along it.

    Each lit step takes its colour from its own place in the ramp rather than
    from the overall level, so the gradient is stable as the bar grows and the
    eye reads length rather than a colour change.
    """
    strip = _ordered(keys)
    intensity = params.flt("intensity")
    lit = int(round(max(0.0, min(1.0, fraction)) * len(strip)))
    out: Frame = {}
    for position, key in enumerate(strip):
        if position < lit:
            step = position / max(1, len(strip) - 1)
            out[key.index] = _scale(_ramp(step, params), intensity)
        else:
            out[key.index] = (0, 0, 0)
    return out


def _rng(params: EffectParams, frame: int) -> random.Random:
    """A generator whose stream depends only on the seed and the frame number.

    Deliberately not a module-level Random: reseeding per frame means a run with
    a given --seed produces byte-identical frames every time, which is the only
    way a sparkle effect can be asserted on in a test.
    """
    return random.Random((int(params.get("seed")) * 6364136223846793005) ^ frame)


# -- decorative effects ----------------------------------------------------


def _solid(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    lit = _scale(params.rgb("color"), params.flt("intensity"))
    return {k.index: lit for k in keys}


def _rainbow(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    phase = elapsed * 0.15 * params.flt("speed")
    intensity = params.flt("intensity")
    reverse = bool(params.get("reverse"))
    return {
        k.index: _scale(_hsv(phase + _position(k, keys, reverse), 1.0, 1.0), intensity)
        for k in keys
    }


def _breathe(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Sine on brightness, floored at 0.05 so the pad never looks switched off.
    level = 0.05 + 0.95 * (0.5 - 0.5 * math.cos(elapsed * 2.0 * params.flt("speed")))
    lit = _scale(params.rgb("color"), level * params.flt("intensity"))
    return {k.index: lit for k in keys}


def _pulse(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Square wave, not a sine: the whole point is a hard edge. `duty` below ~0.1
    # at a high speed is a strobe; at 0.5 and a low speed it is a slow blink.
    cycle = (elapsed * params.flt("speed")) % 1.0
    on = cycle < params.flt("duty")
    lit = _scale(params.rgb("color") if on else params.rgb("secondary_color"),
                 params.flt("intensity"))
    return {k.index: lit for k in keys}


def _chase(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    order = _main_keys(keys)
    if not order:
        return {}
    if params.get("reverse"):
        order = tuple(reversed(order))
    intensity = params.flt("intensity")
    position = int(elapsed * 6.0 * params.flt("speed")) % len(order)
    out: Frame = _dark(keys)
    out[order[position].index] = _scale(params.rgb("color"), intensity)
    # A dim trailing key reads as motion rather than as a key blinking on its own.
    out[order[position - 1].index] = _scale(params.rgb("color"), 0.15 * intensity)
    return out


def _gradient(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Static by design: nine LEDs is too few for a moving gradient to read as
    # anything but flicker. Use `wave` when you want motion.
    intensity = params.flt("intensity")
    reverse = bool(params.get("reverse"))
    return {
        k.index: _scale(_ramp(_position(k, keys, reverse), params), intensity)
        for k in keys
    }


def _wave(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # One full wavelength across the pad, so at any instant there is exactly one
    # crest and one trough visible; more than that on six keys is just noise.
    phase = elapsed * params.flt("speed")
    intensity = params.flt("intensity")
    reverse = bool(params.get("reverse"))
    out: Frame = {}
    for key in keys:
        level = 0.5 - 0.5 * math.cos(2 * math.pi * (_position(key, keys, reverse) - phase))
        out[key.index] = _scale(_ramp(level, params), intensity)
    return out


def _fire(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Flicker is per key and re-rolled on a slow clock, then interpolated: rolling
    # a fresh value every frame at 20fps looks like static rather than flame.
    tick = elapsed * 4.0 * params.flt("speed")
    step, blend = int(tick), tick % 1.0
    intensity = params.flt("intensity")
    out: Frame = {}
    for key in keys:
        a = _noise(params, step, key.index)
        b = _noise(params, step + 1, key.index)
        level = 0.25 + 0.75 * (a + (b - a) * blend)
        # Lower keys sit nearer the "base" of the fire and stay hotter.
        level *= 1.0 - 0.2 * key.row
        out[key.index] = _scale(_ramp(level, params), intensity)
    return out


def _noise(params: EffectParams, step: int, index: int) -> float:
    """Reproducible per-(step, key) value in 0-1.

    A hash rather than a stateful generator so any frame can be computed on its
    own — the render loop must be able to skip frames without the effect drifting.
    """
    h = (int(params.get("seed")) * 2654435761) ^ (step * 40503) ^ (index * 2246822519)
    h &= 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return h / 0xFFFFFFFF


def _twinkle(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Brightness per key lives in scratch and decays in real time rather than per
    # frame, so the look does not change when --fps does.
    levels: dict[int, float] = params.state.setdefault("levels", {})
    last = params.state.get("clock", elapsed)
    params.state["clock"] = elapsed
    dt = max(0.0, elapsed - last)

    rng = _rng(params, frame)
    decay = params.flt("decay") * dt
    chance = params.flt("density") * dt
    intensity = params.flt("intensity")
    out: Frame = {}
    for key in keys:
        level = max(0.0, levels.get(key.index, 0.0) - decay)
        if rng.random() < chance:
            level = 1.0
        levels[key.index] = level
        # Hue jitter per key, held for the life of the spark, keeps the pad from
        # looking like one colour blinking in nine places.
        out[key.index] = _scale(
            _ramp(_noise(params, 7919, key.index), params), level * intensity
        )
    return out


def _ripple(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    strip = _ordered(keys)
    if not strip:
        return {}
    origin = strip[min(int(params.get("origin")), len(strip) - 1)]
    intensity = params.flt("intensity")
    # Rings restart on a fixed period; the radius has to overshoot the pad's
    # diagonal or the last ring vanishes before it reaches the far corner.
    reach = max(1.0, max(abs(k.row - origin.row) + abs(k.col - origin.col) for k in keys))
    period = 1.0 / params.flt("speed")
    radius = ((elapsed % period) / period) * (reach + 1.0)
    out: Frame = {}
    for key in keys:
        distance = abs(key.row - origin.row) + abs(key.col - origin.col)
        # Triangular ring profile one unit wide: sharp enough to read as a ring
        # on a 3x3-ish grid, soft enough not to alias into a single key.
        level = max(0.0, 1.0 - abs(distance - radius))
        out[key.index] = _scale(_ramp(distance / reach, params), level * intensity)
    return out


# -- machine-state effects -------------------------------------------------


def _read_proc_stat() -> tuple[int, int]:
    """Return (busy, idle) cumulative jiffies from the aggregate 'cpu' line.

    Fields after 'cpu' are: user nice system idle iowait irq softirq steal ...
    idle and iowait are both idle time; everything else is busy.
    """
    try:
        with open("/proc/stat", "r") as handle:
            line = handle.readline()
    except OSError as exc:
        raise SdcxError(f"cannot read /proc/stat: {exc}") from exc
    parts = line.split()
    if not parts or parts[0] != "cpu":
        raise SdcxError("/proc/stat did not start with an aggregate 'cpu' line")
    values = [int(v) for v in parts[1:]]
    idle = sum(values[3:5])  # idle + iowait
    return sum(values) - idle, idle


def _smooth(params: EffectParams, key: str, value: float) -> float:
    """Exponential average of successive readings, kept in the effect's scratch.

    Every meter here needs it: a raw ratio measured over one ~50ms frame is
    almost pure noise, and an unsmoothed bar spends its life flickering between
    two keys.
    """
    weight = params.flt("smoothing")
    previous = params.state.get(key)
    result = value if previous is None else previous * weight + value * (1.0 - weight)
    params.state[key] = result
    return result


def _cpu(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # /proc/stat counters are cumulative since boot, so a single sample tells you
    # the average load since boot and nothing about now. Load is the ratio of the
    # busy delta to the total delta between this frame and the previous one.
    busy, idle = _read_proc_stat()
    previous = params.state.get("stat")
    params.state["stat"] = (busy, idle)
    if previous is None:
        return _dark(keys)
    busy_delta = busy - previous[0]
    total_delta = busy_delta + (idle - previous[1])
    load = busy_delta / total_delta if total_delta > 0 else 0.0
    return _bar(keys, _smooth(params, "load", load), params)


def _read_meminfo() -> tuple[int, int]:
    """Return (total_kb, available_kb) from /proc/meminfo.

    MemAvailable rather than MemFree: free memory on Linux is meaningless because
    the page cache eats all of it, and MemAvailable is the kernel's own estimate
    of what a new allocation could actually get.
    """
    fields: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r") as handle:
            for line in handle:
                name, _, rest = line.partition(":")
                if name in ("MemTotal", "MemAvailable"):
                    fields[name] = int(rest.split()[0])
    except OSError as exc:
        raise SdcxError(f"cannot read /proc/meminfo: {exc}") from exc
    except (IndexError, ValueError) as exc:
        raise SdcxError(f"/proc/meminfo is not in the expected format: {exc}") from exc
    if "MemTotal" not in fields or "MemAvailable" not in fields:
        raise SdcxError(
            "/proc/meminfo has no MemAvailable line; this needs Linux 3.14 or newer"
        )
    return fields["MemTotal"], fields["MemAvailable"]


def _probe_meminfo() -> None:
    _read_meminfo()


def _memory(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    total, available = _read_meminfo()
    used = 1.0 - (available / total) if total > 0 else 0.0
    # Smoothed like cpu, though memory moves far more slowly; it costs nothing
    # and stops the top key of the bar twitching when a browser tab allocates.
    return _bar(keys, _smooth(params, "used", used), params)


def _find_temp_source() -> str:
    """Path of the hwmon input to read, preferring a real package sensor.

    hwmon numbering is not stable across boots and the interesting sensor is not
    always hwmon0, so the device name is what picks it. acpitz is last because on
    many laptops it reports a case temperature that barely moves.
    """
    preferred = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
    found: dict[str, str] = {}
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(hwmon, "name"), "r") as handle:
                name = handle.read().strip()
        except OSError:
            continue
        inputs = sorted(glob.glob(os.path.join(hwmon, "temp*_input")))
        if inputs and name not in found:
            found[name] = inputs[0]
    for name in preferred:
        if name in found:
            return found[name]
    if found:
        return next(iter(found.values()))
    raise SdcxError(
        "no CPU temperature sensor found under /sys/class/hwmon; "
        "the 'temperature' effect needs one (try: sensors-detect)"
    )


def _probe_temperature() -> None:
    _find_temp_source()


def _temperature(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    path = params.state.get("temp_path")
    if path is None:
        path = params.state["temp_path"] = _find_temp_source()
    try:
        with open(path, "r") as handle:
            millidegrees = int(handle.read().strip())
    except (OSError, ValueError):
        # The sensor can disappear under us on suspend/resume. A dark pad is a
        # better failure than tearing down the run for a single bad read.
        return _dark(keys)
    celsius = millidegrees / 1000.0
    low, high = params.flt("low"), params.flt("high")
    fraction = 0.0 if high <= low else (celsius - low) / (high - low)
    return _bar(keys, _smooth(params, "temp", max(0.0, min(1.0, fraction))), params)


def _clock(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    """Binary clock.

    How to read it: the six main keys are one 6-bit number, most significant at
    the top-left, reading left to right along the top row and then the bottom.
    Six bits covers 0-63, which is every hour, minute and second value. The knob
    LEDs say which field you are looking at: one lit = hour, two = minute,
    three = second. With --field cycle it steps through all three, --dwell
    seconds each; pin it with --field minute if you only care about one.
    """
    now = time.localtime()
    fields = (("hour", now.tm_hour), ("minute", now.tm_min), ("second", now.tm_sec))
    chosen = params.get("field")
    if chosen == "cycle":
        step = int(elapsed / params.flt("dwell")) % 3
    else:
        step = next(i for i, (name, _) in enumerate(fields) if name == chosen)
    value = fields[step][1]

    intensity = params.flt("intensity")
    on = _scale(params.rgb("color"), intensity)
    marker = _scale(params.rgb("secondary_color"), intensity)
    out: Frame = _dark(keys)
    for position, key in enumerate(_main_keys(keys)[:6]):
        if value & (1 << (5 - position)):
            out[key.index] = on
    for position, key in enumerate(_ordered(keys)[len(_main_keys(keys)):]):
        if position <= step:
            out[key.index] = marker
    return out


EFFECTS: dict[str, Effect] = {
    "solid": Effect(
        "solid", "every key the given colour", _solid,
        help=(
            "The whole pad in one colour. The baseline: use it to check a colour, "
            "or as a calm backlight that the firmware's own modes cannot do "
            "per-key."
        ),
        params=_params("color", "intensity"),
    ),
    "rainbow": Effect(
        "rainbow", "hue sweep across the pad, animated", _rainbow,
        help=(
            "A hue gradient laid across the pad's diagonal and rotated over time. "
            "Ignores --color entirely; --speed sets how fast it turns and "
            "--reverse flips which corner leads."
        ),
        params=_params("speed", "intensity", "reverse"),
    ),
    "breathe": Effect(
        "breathe", "the given colour pulsing in brightness", _breathe,
        help=(
            "One colour rising and falling on a sine, floored just above black so "
            "the pad never looks switched off. Slow it right down (--speed 0.2) "
            "for something you can have on all day."
        ),
        params=_params("color", "speed", "intensity"),
    ),
    "pulse": Effect(
        "pulse", "hard on/off flashing between two colours", _pulse,
        help=(
            "A square wave, not a sine: it snaps between --color and "
            "--secondary-color with no fade. --duty is the fraction of each cycle "
            "spent on the primary, so --duty 0.05 --speed 8 is a strobe and "
            "--duty 0.5 --speed 0.5 is a slow blink. Good as an alarm from a "
            "script; hard to ignore, which is the point."
        ),
        params=_params("color", "secondary_color", "speed", "duty", "intensity"),
    ),
    "chase": Effect(
        "chase", "a lit key running through the six main keys", _chase,
        help=(
            "One bright key running the six switches in order with a dim trailing "
            "key behind it, which is what makes it read as motion rather than as "
            "keys blinking independently. --reverse runs it the other way."
        ),
        params=_params("color", "speed", "intensity", "reverse"),
    ),
    "gradient": Effect(
        "gradient", "static two-colour ramp across the pad", _gradient,
        help=(
            "A still ramp from --color to --secondary-color across the pad's "
            "diagonal, or one of the fixed --palette ramps. Nothing moves, so it "
            "costs no bus traffic after the first frame — the runner only writes "
            "keys that changed. The one to leave running."
        ),
        params=_params("color", "secondary_color", "palette", "intensity", "reverse"),
    ),
    "wave": Effect(
        "wave", "a travelling sine along the pad", _wave,
        help=(
            "One wavelength of a sine travelling across the pad, coloured by the "
            "selected --palette. Exactly one crest is visible at a time: more "
            "than that on six keys aliases into flicker. --reverse changes "
            "direction."
        ),
        params=_params("color", "secondary_color", "palette", "speed", "intensity", "reverse"),
    ),
    "fire": Effect(
        "fire", "warm flickering noise", _fire,
        help=(
            "Per-key flicker on a slow clock, interpolated between rolls so it "
            "looks like flame rather than static, with the lower row biased "
            "hotter as if it were the base of the fire. --seed makes any given "
            "run repeatable."
        ),
        params=_params("palette", "color", "secondary_color", "speed", "intensity", "seed"),
    ),
    "twinkle": Effect(
        "twinkle", "random keys lighting and fading", _twinkle,
        help=(
            "Keys light at random and fade out. --density is how often a key "
            "catches, --decay how fast it fades; both are per second, so the look "
            "is unchanged by --fps. Quiet enough at low density to sit under real "
            "work."
        ),
        params=_params("palette", "color", "secondary_color", "density", "decay", "intensity", "seed"),
    ),
    "ripple": Effect(
        "ripple", "expanding rings from one key", _ripple,
        help=(
            "Rings expanding outward from --origin (a position in the key order, "
            "0-5 for the switches, 6-8 for the knob actions) and repeating. "
            "Distance is measured on the physical grid, so the rings look right "
            "despite the sparse key indices."
        ),
        params=_params("palette", "color", "secondary_color", "origin", "speed", "intensity"),
    ),
    "cpu": Effect(
        "cpu", "heat map of real CPU load from /proc/stat", _cpu,
        help=(
            "A bar across all nine LEDs showing CPU busy time, measured as the "
            "delta between frames — /proc/stat counters are cumulative since "
            "boot, so one sample would only ever tell you the average since boot. "
            "--smoothing controls how twitchy it is."
        ),
        params=_params("palette", "color", "secondary_color", "smoothing", "intensity"),
    ),
    "memory": Effect(
        "memory", "RAM in use, as a bar", _memory,
        help=(
            "Used memory as a fraction of MemTotal, from MemAvailable rather than "
            "MemFree — free memory on Linux is meaningless because the page cache "
            "consumes all of it. Moves slowly; genuinely glanceable."
        ),
        params=_params("palette", "color", "secondary_color", "smoothing", "intensity"),
        probe=_probe_meminfo,
    ),
    "temperature": Effect(
        "temperature", "CPU temperature, cool to hot", _temperature,
        help=(
            "CPU package temperature from /sys/class/hwmon, as a bar between "
            "--low and --high degrees Celsius (default 35-85). The sensor is "
            "chosen by hwmon device name, not by number, because hwmon numbering "
            "shuffles between boots."
        ),
        params=_params("palette", "color", "secondary_color", "low", "high", "smoothing", "intensity"),
        probe=_probe_temperature,
    ),
    "clock": Effect(
        "clock", "the time, in binary, across the pad", _clock,
        help=(
            "Binary clock. The six switches are one 6-bit number, most "
            "significant at top-left, reading left to right along the top row "
            "then the bottom; six bits covers 0-63, so every hour, minute and "
            "second value fits. The knob LEDs say which field is showing: one lit "
            "= hour, two = minute, three = second. --field cycle steps through all "
            "three every --dwell seconds; --field minute pins it to one."
        ),
        params=_params("color", "secondary_color", "field", "dwell", "intensity"),
    ),
}


# -- the CLI and GUI surface -----------------------------------------------


def register_effect_arguments(parser: argparse.ArgumentParser) -> None:
    """Add a flag for the union of every effect's parameters.

    Called from cli.py on the `effect` subparser. It is deliberately idempotent
    and tolerant of collisions: `--color` is already defined there, and a GUI or
    a test may call this twice on the same parser. Defaults stay None so that
    run_effect can tell "the user did not pass this" from "the user passed the
    value that happens to equal the default", and fall back to the effect's own
    declared default in the first case.
    """
    for param in PARAM_LIBRARY.values():
        if param.flag in parser._option_string_actions:
            continue
        options: dict[str, Any] = {"default": None, "help": param.description}
        if param.kind == "bool":
            options["action"] = "store_true"
        elif param.kind == "choice":
            options["choices"] = list(param.choices or ())
            options["metavar"] = "{" + ",".join(param.choices or ()) + "}"
        elif param.kind == "color":
            options["metavar"] = "#RRGGBB"
        else:
            options["type"] = float if param.kind == "float" else int
            options["metavar"] = param.kind.upper()
        try:
            parser.add_argument(param.flag, **options)
        except argparse.ArgumentError:
            # Another caller got there first with a different spelling of the
            # same flag. Theirs wins; the coercion below copes either way.
            continue


def effects_manifest() -> list[dict]:
    """Every effect, fully self-describing, as JSON-serialisable dicts.

    This is the contract with the GUI: it renders controls from `params` and
    hover text from `help` without knowing anything about the effects themselves,
    so an effect added here appears there with no matching change.
    """
    return [effect.to_dict() for effect in EFFECTS.values()]


def resolve_params(effect: Effect, args) -> EffectParams:
    """Collect this effect's declared parameters off an argparse namespace.

    Only the parameters the effect declares are read. Flags belonging to other
    effects are ignored rather than rejected, which is what lets one shared set
    of flags serve fourteen effects — `sdcx effect solid --density 0.9` is
    harmless rather than an error.
    """
    values: dict[str, Any] = {}
    for param in effect.params:
        values[param.name] = param.coerce(getattr(args, param.name, None))
    fps = min(max(float(getattr(args, "fps", 20.0) or 20.0), 1.0), MAX_FPS)
    color = values.get("color") or parse_hex_color(
        getattr(args, "color", None) or "#7c4dff"
    )
    return EffectParams(color=color, fps=fps, values=values)


# -- the runner ------------------------------------------------------------


def run_effect(args) -> int:
    """Run one effect until its duration expires or the user interrupts."""
    effect = EFFECTS.get(args.name)
    if effect is None:
        raise SdcxError(
            f"unknown effect {args.name!r}. Available: {', '.join(EFFECTS)} "
            "(or 'list' for descriptions)"
        )

    # Before the device is touched, so an effect whose data source is missing on
    # this machine says so and leaves the pad alone rather than switching it to
    # Custom mode and then dying on the first frame.
    if effect.probe is not None:
        effect.probe()

    params = resolve_params(effect, args)
    fps = params.fps
    duration = float(getattr(args, "duration", 0.0) or 0.0)

    frames = 0
    interrupted = False

    # An effect is normally stopped by something else killing it — Ctrl-C from a
    # shell, but SIGTERM from the Quickshell widget's stop button. The default
    # SIGTERM disposition kills the process outright, which would skip the
    # restore below and strand the pad mid-effect, so route it through the same
    # unwinding path as Ctrl-C.
    def _terminate(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    previous_handler = signal.signal(signal.SIGTERM, _terminate)

    try:
        return _render_loop(args, effect, params, fps, duration, frames, interrupted)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def _render_loop(
    args,
    effect: "Effect",
    params: "EffectParams",
    fps: float,
    duration: float,
    frames: int,
    interrupted: bool,
) -> int:
    with Keypad.open(path=args.device) as pad:
        keys = pad.layout.keys
        if not keys:
            raise SdcxError(
                f"{pad.layout.model} has no verified key map, so per-key effects "
                "cannot address it. Global lighting still works: sdcx light mode"
            )

        previous_light = pad.get_light() if getattr(args, "restore", False) else None
        try:
            pad.set_light_mode(CUSTOM_MODE)
            start = time.monotonic()
            # Only the keys that actually changed are written. For a mostly
            # static frame (cpu at idle, a slow chase, gradient after its first
            # frame) that turns nine transfers per frame into one or two, keeping
            # bus traffic proportional to visible change rather than to fps.
            shown: Frame = {}
            while True:
                now = time.monotonic()
                elapsed = now - start
                if duration > 0 and elapsed >= duration:
                    break
                for index, rgb in effect.render(frames, elapsed, keys, params).items():
                    if shown.get(index) != rgb:
                        pad.set_key_color(index, rgb)
                        shown[index] = rgb
                frames += 1
                # Sleep on the frame deadline, not a fixed interval, so render
                # cost does not accumulate into drift.
                delay = (start + frames / fps) - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if previous_light is not None:
                pad.set_light(previous_light)

    payload = {
        "ok": True,
        "effect": effect.name,
        "frames": frames,
        "fps": fps,
        "interrupted": interrupted,
        "restored": previous_light is not None,
        "params": {
            name: ("#%02x%02x%02x" % value if isinstance(value, tuple) else value)
            for name, value in params.values.items()
        },
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"{effect.name}: {frames} frames" + (" (interrupted)" if interrupted else ""))
    return 0
