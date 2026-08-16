<div align="center">

# sdcx-keypad

Linux driver and CLI for SDCX / SDINNOVATION programmable macro keypads.

![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Linux-informational?style=for-the-badge)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen?style=for-the-badge)

</div>

`sdcx` is a command-line driver for the family of six-key macro keypads with a rotary encoder
sold under the SDCX / SDINNOVATION protocol, often unbranded, on AliExpress, Amazon, and similar
marketplaces. These devices ship with a Windows-only configurator or a web-based one, with no
Linux support. `sdcx` talks to the keypad's vendor HID interface directly: it turns the lighting
off permanently, changes modes and colours, remaps keys and macros, and drives per-key colour
from the host. It is written in the Python standard library, with no runtime dependencies.

```bash
sdcx light off
```

This writes one report to the device, which stores it in flash. The setting survives unplugging
and rebooting; the keys keep working and only the LEDs go dark.

---

## Contents

- [Does this work with my keypad?](#does-this-work-with-my-keypad)
- [Install](#install)
- [Permissions](#permissions)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Key layout: HCY-K006](#key-layout-hcy-k006)
- [Keymaps and macros](#keymaps-and-macros)
- [Live effects](#live-effects)
- [Light modes (HCY-K006)](#light-modes-hcy-k006)
- [How it works](#how-it-works)
- [Integrations: panels, widgets, scripts](#integrations-panels-widgets-scripts)
- [Safety](#safety)
- [Contributing](#contributing)
- [Licence](#licence)

---

## Does this work with my keypad?

Check the USB ID with `lsusb`:

```bash
lsusb
# Bus 001 Device 007: ID 0816:246f SDINNOVATION SIDE-KEYBOARD
```

Then ask the tool directly:

```bash
sdcx list
# /dev/hidraw4  0816:246f  HCY-K006
```

If `sdcx list` prints a device, it is supported. If it prints nothing while a keypad is plugged
in, the USB ID may not be in the recognised list yet; see
[reporting a device](docs/DEVICES.md#reporting-a-device).

Support falls into two tiers:

- **196 USB IDs across 32 vendor IDs are recognised**, the same set the vendor's own WebHID
  configurator accepts. These pads are sold under dozens of unbranded names; the silicon and the
  protocol are shared across them.
- **One device is hardware-verified: `0816:246f` (HCY-K006)**, six keys plus a clickable rotary
  encoder, identifying as `SIDE-KEYBOARD` / `SDINNOVATION`. Every other recognised ID uses the
  **generic fallback**: global lighting (off, mode, brightness, speed, colour) works, because it
  is identical across the family, but per-key operations report that the layout is unknown
  rather than guessing at key indices. `sdcx list` marks these `(layout unverified)`.

Indicators that a device belongs to this family: a vendor-defined HID interface on usage page
`0xFF00`, a configurator that is a website rather than a native app, or packaging naming SDCX,
SDINNOVATION, or Shenzhen HCY.

The full device list, and how "verified" differs from "recognised", is in
[`docs/DEVICES.md`](docs/DEVICES.md).

---

## Install

```bash
# recommended: isolated, on PATH
pipx install git+https://github.com/parsaj-dev/sdcx-keypad

# or plain pip
pip install git+https://github.com/parsaj-dev/sdcx-keypad

# or from a checkout
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
pip install .

# or no install at all: there are no dependencies to install
python3 -m sdcx --help
```

Requirements: **Linux** (it uses `/dev/hidraw` and `/sys/class/hidraw`) and **Python 3.11+**.
Nothing else.

<details>
<summary>Nix / NixOS</summary>

The flake exposes `packages.default` and a `nixosModules.default` that installs the tool
system-wide and ships the udev rule:

```nix
{
  inputs.sdcx-keypad.url = "github:parsaj-dev/sdcx-keypad";

  # in your configuration:
  imports = [ inputs.sdcx-keypad.nixosModules.default ];
}
```

Or run it without installing:

```bash
nix run github:parsaj-dev/sdcx-keypad -- list
```

</details>

---

## Permissions

The keypad's configuration interface is owned by root by default, so a fresh `sdcx light off`
fails with a permission error until this is fixed. That is expected on a first run, not a bug.

One-off test, resets on unplug:

```bash
sdcx list                     # find the hidraw node, e.g. /dev/hidraw4
sudo chmod 666 /dev/hidraw4
```

Permanent fix, a udev rule that tags the vendor configuration interface `uaccess` and grants the
`input` group access:

```bash
sdcx install-udev-rule --print          # inspect the rule before writing it
sudo sdcx install-udev-rule             # writes /etc/udev/rules.d/70-sdcx-keypad.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# unplug and replug the keypad
```

The rule matches only `hidraw` nodes belonging to recognised keypad USB IDs. Keyboard input
interfaces are untouched.

On NixOS and other distributions that generate `/etc` declaratively, `/etc/udev/rules.d` is
read-only. `sdcx install-udev-rule` detects this (`EROFS` on write) and prints the declarative
equivalent instead of failing silently:

```nix
# flake.nix
inputs.sdcx-keypad.url = "github:parsaj-dev/sdcx-keypad";
# in the host configuration:
imports = [ inputs.sdcx-keypad.nixosModules.default ];
programs.sdcx-keypad.enable = true;
```

or, without adding a flake input:

```nix
services.udev.extraRules = ''
  KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0816", TAG+="uaccess"
'';
```

followed by `sudo nixos-rebuild switch` and a replug. `sdcx install-udev-rule --print` prints the
exhaustive rule covering every supported USB ID for use in either path.

---

## Quick start

```bash
sdcx list                              # is it there, and on which hidraw node
sdcx info                              # firmware, serial, active profile, auto-sleep
sdcx light off                         # turn off the RGB, persists across reboots
sdcx light get                         # current lighting state
sdcx light mode breath                 # switch effect, using the firmware's own defaults
sdcx light set --brightness 2 --color '#ff8800'
sdcx light mode custom                 # hand per-key colour control to the host
sdcx key color all '#101010'           # set every key to a faint glow
```

Every command also accepts `--json`, for use from scripts and panels.

---

## Command reference

Two flags are global and precede the subcommand:

| flag | meaning |
|---|---|
| `--json` | print a single JSON object on stdout, including on failure, with a non-zero exit code |
| `--device PATH` | use a specific hidraw node; default is the first keypad found |

```bash
sdcx --json light get
sdcx --device /dev/hidraw4 light off
```

### Discovery and inspection

| command | description |
|---|---|
| `sdcx list` | connected keypads: hidraw path, USB ID, model, and whether the layout is verified. Exit code 1 if none found. |
| `sdcx info` | firmware version, serial, active profile and layer, auto-sleep time |
| `sdcx modes` | the lighting modes this device's firmware implements, and which fields each honours |
| `sdcx keys` | addressable keys: index and label |
| `sdcx keys --colors` | addressable keys, including each key's current colour read back off the device |

### Global lighting

```bash
sdcx light get                  # current mode, brightness, speed, colour
sdcx light off                  # mode 0
sdcx light mode breath          # by name (case-insensitive) or by number
sdcx light mode 2
```

`light mode` reproduces what the vendor UI does: it requests the firmware's preferred defaults
for that mode and writes those back, so switching effects matches the web app's behaviour.

`light set` changes individual fields on top of the current state and leaves the rest unchanged:

```bash
sdcx light set --brightness 4
sdcx light set --mode steady --color '#ff8800'
sdcx light set --speed 1 --direction 0
sdcx light set --palette                     # rainbow palette instead of a single colour
```

| flag | values |
|---|---|
| `--mode` | mode name or number |
| `--brightness` | `0`-`4` |
| `--speed` | `0`-`4` |
| `--direction` | `0` or `1` |
| `--color` | `#RRGGBB`, also switches to single-colour mode |
| `--palette` | switch back to the rainbow palette |

### Per-key colour

```bash
sdcx key color 0 '#00ff00'      # one key, by index
sdcx key color all '#101010'    # every key on the layout
```

Per-key colour is only visible in Custom mode (`sdcx light mode custom`). In any other mode the
on-device effect engine repaints the LEDs over host writes, so changes appear to do nothing.

Key indices are sparse: see [Key layout: HCY-K006](#key-layout-hcy-k006). `sdcx keys` lists the
indices for the connected device.

### Keymaps

```bash
sdcx keymap get                       # show each key's current binding
sdcx keymap get --layer 1             # a specific layer
sdcx keymap set 0 ctrl+c              # rebind key 0 to Ctrl+C
sdcx keymap set 1 macro:3             # bind key 1 to macro slot 3
sdcx keymap reset                     # restore the firmware's own key table
```

`keymap set` accepts a keycode name, a `+`-joined combination such as `ctrl+shift+a`, or
`macro:N` to bind a key to a stored macro slot. `keymap get`, `keymap set`, and `keymap reset` all
accept `--layer LAYER` to target a specific layer.

### Keycodes

```bash
sdcx keycodes                         # every keycode name 'keymap set' accepts
sdcx keycodes --category media        # one category only
sdcx keycodes --search volume         # substring match on name or code
```

Categories: `keyboard`, `media`, `mouse`, `system`, `control`, `macro`, `special`.

<details>
<summary>Keycode categories, with examples</summary>

| category | examples |
|---|---|
| `keyboard` | `a`-`z`, `0`-`9`, `comma`, `bracket_left`, `alt_left`, `control_right`, `f1`-`f24`, arrow keys |
| `media` | `volume_up`, `volume_down`, `mute`, `play_pause`, `next_track`, `web_search`, `screen_brightness_up` |
| `mouse` | mouse buttons and movement |
| `system` | system power and sleep keys |
| `control` | modifier and control keys |
| `macro` | references into macro slots |
| `special` | `disabled` and other non-standard codes |

Run `sdcx keycodes` for the authoritative, complete list; it is generated from the firmware's own
keycode table and may grow between releases.

</details>

### Macros

```bash
sdcx macro get                             # show stored macros
sdcx macro get --all                       # include empty slots
sdcx macro get --raw                       # dump the raw 4096-byte macro area
sdcx macro set 3 'ctrl+c, a'               # record slot 3: Ctrl+C, then A
sdcx macro set 3 'ctrl+c, a' --delay 50    # 50ms between events
sdcx macro reset                           # clear every macro slot
```

`macro set` takes a slot number from `0` to `31` and a comma-separated sequence of keystrokes,
each pressed and released in turn. Bind a macro to a key with `sdcx keymap set <index> macro:<slot>`.

### Device settings

```bash
sdcx profile 0                  # select a configuration scheme (0-based)
sdcx sleep 300                  # auto-sleep after N seconds
sdcx factory-reset --yes        # erase keymap, macros, and per-key colours
```

`factory-reset` refuses to run without `--yes`.

### Permissions helper

```bash
sdcx install-udev-rule --print  # print the rule to stdout, write nothing
sudo sdcx install-udev-rule     # write /etc/udev/rules.d/70-sdcx-keypad.rules
```

### Reporting a device

```bash
sdcx report                     # markdown block, ready to paste into an issue
sdcx report --json              # the same data as JSON
```

`report` reads the device and writes nothing to it. It collects the USB descriptor
strings, the firmware configuration, the current lighting state, the keymap and the
per-key colours, and formats them for a bug report. Only one of the 196 recognised
USB IDs has been verified against real hardware, so a report from any other device
is useful. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Key layout: HCY-K006

Six switches in two rows of three, plus a clickable rotary encoder. Index `17` is the encoder
turned clockwise, `18` is counter-clockwise, `16` is the encoder press.

```text
   ┌───────┐   ┌───────┐   ┌───────┐        ┌─────────┐
   │   0   │   │   1   │   │   2   │        │   17 ↻  │
   └───────┘   └───────┘   └───────┘        │ 16  ●   │
   ┌───────┐   ┌───────┐   ┌───────┐        │   18 ↺  │
   │   3   │   │   4   │   │   5   │        └─────────┘
   └───────┘   └───────┘   └───────┘         rotary encoder
```

The vendor's own layout JSON labels the encoder directions the other way round; that labelling is
incorrect. On the physical HCY-K006, index `17` fires on a clockwise turn (volume up in the
factory keymap) and `18` fires counter-clockwise (volume down).

---

## Live effects

Live effects run on the host, one frame at a time, and are pushed to the pad as per-key colours.
The device's built-in effects cannot do this, because they have no knowledge of the host; this is
also what makes host-driven effects like a CPU heat map possible at all.

```bash
sdcx effect list
sdcx effect cpu                                  # CPU load heat map from /proc/stat
sdcx effect rainbow --fps 30
sdcx effect breathe --color '#7c4dff' --restore
sdcx effect chase --duration 10
```

The runner switches the device into Custom mode automatically and writes only the keys whose
colour changed since the last frame, so a mostly-static frame costs one or two transfers instead
of nine. `Ctrl-C` and `SIGTERM` both stop it cleanly.

| effect | description |
|---|---|
| `solid` | every key the given colour |
| `rainbow` | hue sweep across the pad, animated |
| `breathe` | the given colour pulsing in brightness |
| `pulse` | hard on/off flashing between two colours |
| `chase` | a lit key running through the six main keys |
| `gradient` | static two-colour ramp across the pad |
| `wave` | a travelling sine along the pad |
| `fire` | warm flickering noise |
| `twinkle` | random keys lighting and fading |
| `ripple` | expanding rings from one key |
| `cpu` | heat map of real CPU load from `/proc/stat` |
| `memory` | RAM in use, as a bar |
| `temperature` | CPU temperature, cool to hot |
| `clock` | the time, in binary, across the pad |

<details>
<summary>Effect details and parameters</summary>

**`solid`**: every key the given colour. The baseline: use it to check a colour, or as a calm
backlight that the firmware's own modes cannot do per-key.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`rainbow`**: a hue gradient laid across the pad's diagonal and rotated over time. Ignores
`--color`; `--speed` sets how fast it turns and `--reverse` flips which corner leads.

| flag | default | range | meaning |
|---|---|---|---|
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier; `1.0` is the effect's natural pace |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |
| `--reverse` | off | | run the motion the other way along the pad |

**`breathe`**: one colour rising and falling on a sine, floored just above black so the pad never
looks switched off. Slow it right down (`--speed 0.2`) for something to leave on all day.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`pulse`**: a square wave, not a sine: it snaps between `--color` and `--secondary-color` with
no fade. `--duty` is the fraction of each cycle spent on the primary colour, so `--duty 0.05
--speed 8` is a strobe and `--duty 0.5 --speed 0.5` is a slow blink. Useful as an alarm driven
from a script.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier |
| `--duty` | `0.5` | `0.02`-`0.98` | fraction of each cycle spent lit |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`chase`**: one bright key running the six switches in order with a dim trailing key behind it,
which reads as motion rather than as keys blinking independently. `--reverse` runs it the other
way.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |
| `--reverse` | off | | run the motion the other way along the pad |

**`gradient`**: a still ramp from `--color` to `--secondary-color` across the pad's diagonal, or
one of the fixed `--palette` ramps. Nothing moves, so it costs no bus traffic after the first
frame; the runner only writes keys that changed.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp; `custom` interpolates primary to secondary, the rest are fixed ramps that ignore both colours |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |
| `--reverse` | off | | run the motion the other way along the pad |

**`wave`**: one wavelength of a sine travelling across the pad, coloured by the selected
`--palette`. Exactly one crest is visible at a time; more than that on six keys aliases into
flicker. `--reverse` changes direction.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |
| `--reverse` | off | | run the motion the other way along the pad |

**`fire`**: per-key flicker on a slow clock, interpolated between rolls so it looks like flame
rather than static, with the lower row biased hotter as if it were the base of the fire.
`--seed` makes a given run repeatable.

| flag | default | range | meaning |
|---|---|---|---|
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |
| `--seed` | `0` | `0`-`2147483647` | seed for randomised effects; the same seed and fps replays the same frames exactly |

**`twinkle`**: keys light at random and fade out. `--density` is how often a key catches,
`--decay` how fast it fades; both are per second, so the look is unchanged by `--fps`. Quiet at
low density.

| flag | default | range | meaning |
|---|---|---|---|
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--density` | `0.25` | `0.0`-`1.0` | how often a new key lights per second, per key |
| `--decay` | `0.5` | `0.05`-`5.0` | how fast a lit key fades, in brightness per second |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |
| `--seed` | `0` | `0`-`2147483647` | seed for randomised effects |

**`ripple`**: rings expanding outward from `--origin` (a position in the key order, `0`-`5` for
the switches, `6`-`8` for the knob actions) and repeating. Distance is measured on the physical
grid, so the rings look right despite the sparse key indices.

| flag | default | range | meaning |
|---|---|---|---|
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--origin` | `4` | `0`-`8` | key to radiate from, as a position in the main-key order |
| `--speed` | `1.0` | `0.05`-`20.0` | animation rate multiplier |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`cpu`**: a bar across all nine LEDs showing CPU busy time, measured as the delta between
frames, since `/proc/stat` counters are cumulative since boot and a single sample would only give
the average since boot. `--smoothing` controls how twitchy it is.

| flag | default | range | meaning |
|---|---|---|---|
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--smoothing` | `0.7` | `0.0`-`0.99` | how much of the previous reading a meter keeps; higher is calmer and slower to react |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`memory`**: used memory as a fraction of `MemTotal`, computed from `MemAvailable` rather than
`MemFree`, since free memory on Linux is not meaningful because the page cache consumes it.
Moves slowly.

| flag | default | range | meaning |
|---|---|---|---|
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--smoothing` | `0.7` | `0.0`-`0.99` | how much of the previous reading a meter keeps |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`temperature`**: CPU package temperature from `/sys/class/hwmon`, shown as a bar between
`--low` and `--high` degrees Celsius (default 35 to 85). The sensor is chosen by hwmon device
name, not by number, since hwmon numbering shuffles between boots.

| flag | default | range | meaning |
|---|---|---|---|
| `--palette` | `custom` | `custom`, `rainbow`, `fire`, `ice`, `mono` | colour ramp |
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--low` | `35.0` | `-50.0`-`200.0` | reading mapped to the cold end of the ramp |
| `--high` | `85.0` | `-50.0`-`200.0` | reading mapped to the hot end of the ramp |
| `--smoothing` | `0.7` | `0.0`-`0.99` | how much of the previous reading a meter keeps |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

**`clock`**: a binary clock. The six switches are one 6-bit number, most significant bit at
top-left, reading left to right along the top row then the bottom row; six bits covers 0 to 63,
which fits every hour, minute and second value. The knob LEDs indicate which field is showing:
one lit means hour, two means minute, three means second. `--field cycle` steps through all three
every `--dwell` seconds; `--field minute` pins it to one field.

| flag | default | range | meaning |
|---|---|---|---|
| `--color` | `#7c4dff` | | primary colour |
| `--secondary-color` | `#00e5ff` | | second colour |
| `--field` | `cycle` | `cycle`, `hour`, `minute`, `second` | which part of the time to show |
| `--dwell` | `2.0` | `0.5`-`30.0` | seconds each field is displayed before the next one |
| `--intensity` | `1.0` | `0.0`-`1.0` | overall brightness ceiling |

</details>

Two flags apply across every effect and are not effect-specific: `--fps` (frames per second,
clamped to 1 through 60, default `20.0`) and `--duration` (seconds to run; `0`, the default, runs
until interrupted).

Adding a new effect is a single render function in
[`sdcx/effects.py`](sdcx/effects.py): given a frame number, elapsed time, and the key list, return
a `{key_index: (r, g, b)}` dict.

---

## Light modes (HCY-K006)

The checkmarks are the firmware's own capability flags: which fields it honours in that mode.
Other devices in the family may expose a different set; `sdcx modes` reports the connected
device's own set.

| value | name | 中文 | brightness | speed | direction | colour | palette |
|---|---|---|---|---|---|---|---|
| 0 | Off | 关闭 | | | | | |
| 1 | Steady | 常亮 | ✓ | | | ✓ | ✓ |
| 2 | Breath | 呼吸 | ✓ | ✓ | | ✓ | ✓ |
| 3 | Press-lit | 按亮 | ✓ | ✓ | | ✓ | ✓ |
| 4 | Tidal | 潮汐 | ✓ | ✓ | | ✓ | ✓ |
| 5 | Custom | custom | ✓ | | | | ✓ |

Mode 5 hands per-key colour control to the host.

---

## How it works

Alongside its keyboard interfaces, the keypad exposes a vendor-defined HID interface on usage
page `0xFF00`, carrying 64-byte reports with report ID 0. On Linux this is a single
`/dev/hidrawN` node accessed with a `read()`/`write()` pair, which is why this package needs no
HID binding, no `libusb`, and no third-party packages at all.

The protocol was not reverse-engineered from USB captures. The vendor ships a WebHID
configurator at `sdcx-tech.com` whose JavaScript bundle contains the whole device API in readable
form: command bytes, field offsets, per-device capability JSON, and the accepted USB ID list. It
was read out of the web app and reimplemented. Packet layouts, the firmware quirks the web app
works around, and where each constant came from are documented in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md).

Two implementation details worth knowing: device discovery matches on the report descriptor
rather than an interface number, so a firmware revision that reorders interfaces will not break
it; and unsolicited `AA FA` lighting notifications from the device are recognised and skipped, so
turning the knob mid-command does not corrupt a reply.

---

## Integrations: panels, widgets, scripts

Every subcommand accepts `--json` and returns one object carrying an `ok` field, errors included,
so scripts never need to parse human-readable prose. That makes it straightforward to drive from
waybar, eww, polybar, a keybind, a systemd unit, or a plain shell script:

```bash
sdcx --json light get | jq -r .mode_name
```

An optional [Quickshell](https://quickshell.org) overlay widget built on exactly that interface
lives in [`quickshell/`](quickshell/) as a worked example; see
[`quickshell/README.md`](quickshell/README.md). It is entirely optional and nothing in the CLI
depends on it.

---

## Safety

Firmware update is documented but deliberately not implemented. Command groups `0x55` and `0x5A`
are the bootloader and flash path. They are described in [`docs/PROTOCOL.md`](docs/PROTOCOL.md)
for completeness, and nothing in this package can send them. A mistake in that path bricks the
device with no recovery short of hardware intervention. See [CONTRIBUTING.md](CONTRIBUTING.md)
before proposing to add them.

`factory-reset` is implemented. It discards the keymap, macros, and per-key colours, which is why
it is gated behind `--yes`.

Everything else in this package writes only to the vendor configuration interface of a device
plugged into the local machine.

---

## Contributing

New devices, transcribed key layouts, and bug reports are welcome, especially a report of the
form "this works on my pad, here is the `lsusb` line." See [CONTRIBUTING.md](CONTRIBUTING.md),
and use the [new device report](.github/ISSUE_TEMPLATE/new-device.md) template.

---

## Licence

MIT. See [LICENSE](LICENSE).
