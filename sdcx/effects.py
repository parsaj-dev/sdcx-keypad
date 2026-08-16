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

See docs/PROTOCOL.md §3 for the underlying commands.
"""

from __future__ import annotations

import colorsys
import json
import math
import signal
import time
from dataclasses import dataclass, field
from typing import Callable

from .device import SdcxError
from .layouts import Key
from .protocol import Keypad, parse_hex_color

CUSTOM_MODE = 5

# Above this the transfers stop being visible as separate frames and only cost
# bus bandwidth; the LEDs themselves are nowhere near this responsive.
MAX_FPS = 60.0

Rgb = tuple[int, int, int]
Frame = dict[int, Rgb]


@dataclass
class EffectParams:
    """Everything a render function is allowed to depend on besides time.

    `state` is per-run mutable scratch, owned by the effect. It exists for
    effects that are not pure functions of the clock — `cpu` keeps its previous
    /proc/stat sample there.
    """

    color: Rgb = (0x7C, 0x4D, 0xFF)
    fps: float = 20.0
    state: dict = field(default_factory=dict)


RenderFn = Callable[[int, float, tuple[Key, ...], EffectParams], Frame]


@dataclass(frozen=True)
class Effect:
    name: str
    description: str
    render: RenderFn


# -- colour helpers --------------------------------------------------------


def _hsv(h: float, s: float, v: float) -> Rgb:
    """h wraps, s and v clamp. All 0-1."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return round(r * 255), round(g * 255), round(b * 255)


def _scale(rgb: Rgb, factor: float) -> Rgb:
    factor = max(0.0, min(1.0, factor))
    return round(rgb[0] * factor), round(rgb[1] * factor), round(rgb[2] * factor)


def _main_keys(keys: tuple[Key, ...]) -> tuple[Key, ...]:
    """The six switches, in label order; knobs are separate on the K006."""
    return tuple(k for k in keys if k.kind == "key")


# -- effects ---------------------------------------------------------------


def _solid(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    return {k.index: params.color for k in keys}


def _rainbow(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Spatial phase comes from the physical position, not the key index, because
    # the index is sparse (0-5 then 16-18) and would leave a gap in the sweep.
    span = max(1, max(k.row + k.col for k in keys))
    return {
        k.index: _hsv((elapsed * 0.15) + (k.row + k.col) / (span + 1), 1.0, 1.0)
        for k in keys
    }


def _breathe(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # Sine on brightness, floored at 0.05 so the pad never looks switched off.
    level = 0.05 + 0.95 * (0.5 - 0.5 * math.cos(elapsed * 2.0))
    lit = _scale(params.color, level)
    return {k.index: lit for k in keys}


def _chase(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    order = _main_keys(keys)
    if not order:
        return {}
    position = int(elapsed * 6.0) % len(order)
    out: Frame = {k.index: (0, 0, 0) for k in keys}
    out[order[position].index] = params.color
    # A dim trailing key reads as motion rather than as a key blinking on its own.
    out[order[position - 1].index] = _scale(params.color, 0.15)
    return out


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


def _cpu(frame: int, elapsed: float, keys: tuple[Key, ...], params: EffectParams) -> Frame:
    # /proc/stat counters are cumulative since boot, so a single sample tells you
    # the average load since boot and nothing about now. Load is the ratio of the
    # busy delta to the total delta between this frame and the previous one.
    busy, idle = _read_proc_stat()
    previous = params.state.get("stat")
    params.state["stat"] = (busy, idle)
    if previous is None:
        return {k.index: (0, 0, 0) for k in keys}
    busy_delta = busy - previous[0]
    total_delta = busy_delta + (idle - previous[1])
    load = busy_delta / total_delta if total_delta > 0 else 0.0

    # Smoothed, because a raw per-frame ratio over a ~50ms window is pure noise.
    smoothed = params.state.get("load", load) * 0.7 + load * 0.3
    params.state["load"] = smoothed

    lit = int(round(smoothed * len(keys)))
    ordered = _main_keys(keys) + tuple(k for k in keys if k.kind != "key")
    out: Frame = {}
    for position, key in enumerate(ordered):
        if position < lit:
            # Hue 0.33 (green) down to 0.0 (red) across the bar: how hot this
            # particular step is, not the overall load, so the gradient is stable.
            fraction = position / max(1, len(ordered) - 1)
            out[key.index] = _hsv(0.33 * (1.0 - fraction), 1.0, 1.0)
        else:
            out[key.index] = (0, 0, 0)
    return out


EFFECTS: dict[str, Effect] = {
    "solid": Effect("solid", "every key the given colour", _solid),
    "rainbow": Effect("rainbow", "hue sweep across the pad, animated", _rainbow),
    "breathe": Effect("breathe", "the given colour pulsing in brightness", _breathe),
    "chase": Effect("chase", "a lit key running through the six main keys", _chase),
    "cpu": Effect("cpu", "heat map of real CPU load from /proc/stat", _cpu),
}


# -- the runner ------------------------------------------------------------


def run_effect(args) -> int:
    """Run one effect until its duration expires or the user interrupts."""
    effect = EFFECTS.get(args.name)
    if effect is None:
        raise SdcxError(
            f"unknown effect {args.name!r}. Available: {', '.join(EFFECTS)} "
            "(or 'list' for descriptions)"
        )

    fps = min(max(float(getattr(args, "fps", 20.0) or 20.0), 1.0), MAX_FPS)
    duration = float(getattr(args, "duration", 0.0) or 0.0)
    params = EffectParams(color=parse_hex_color(args.color), fps=fps)

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
            # static frame (cpu at idle, a slow chase) that turns nine transfers
            # per frame into one or two, keeping bus traffic proportional to
            # visible change rather than to fps.
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
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"{effect.name}: {frames} frames" + (" (interrupted)" if interrupted else ""))
    return 0
