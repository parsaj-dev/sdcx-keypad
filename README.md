# sdcx-keypad — Linux driver and CLI for SDCX / SDINNOVATION macro keypads

Turn off the RGB, set per-key colours, and configure cheap AliExpress/Amazon macropads from
Linux — no Windows software, no browser, no dependencies.

![license MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![platform Linux](https://img.shields.io/badge/platform-Linux-informational)
![dependencies none](https://img.shields.io/badge/dependencies-none-brightgreen)

You bought a six-key macro keypad with a knob. It came with a Windows `.exe`, or a link to a
web configurator at **sdcx-tech.com**, and nothing that works on Linux. `lsusb` shows something
like `0816:246f`, the product string is **`SIDE-KEYBOARD`**, the manufacturer is
**`SDINNOVATION`**, and the box says **HCY-K006** (Shenzhen HCY, szhcykb.com). Its LEDs are
blazing away and you would like them to stop.

This is a small command-line driver for that whole family of keypads. It speaks the vendor's own
HID configuration protocol directly, so it can turn the lighting off permanently, change modes
and colours, address individual keys, and run host-computed light shows. It is pure Python
standard library — no `hidapi`, no `libusb`, no pip dependencies at all.

The command almost everyone came here for:

```bash
sdcx light off
```

That writes one report, the keypad stores it in flash, and it survives unplugging and rebooting.
The keys keep working; only the LEDs go dark.

## Contents

- [Does this work with my keypad?](#does-this-work-with-my-keypad)
- [Install](#install)
- [Permissions (read this first)](#permissions-read-this-first)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Live effects](#live-effects)
- [Light modes (HCY-K006)](#light-modes-hcy-k006)
- [How it works](#how-it-works)
- [Integrations: panels, widgets, scripts](#integrations-panels-widgets-scripts)
- [Safety](#safety)
- [Contributing](#contributing)
- [Licence](#licence)

## Does this work with my keypad?

Plug it in and look at the USB ID:

```bash
lsusb
# Bus 001 Device 007: ID 0816:246f SDINNOVATION SIDE-KEYBOARD
```

Then ask the tool directly:

```bash
sdcx list
# /dev/hidraw4  0816:246f  HCY-K006
```

If `sdcx list` prints a device, you are in business. If it says nothing is found while a keypad
is plugged in, the USB ID may simply not be in the list yet — see
[reporting a device](docs/DEVICES.md#reporting-a-device).

**The short version of what is supported:**

- **196 USB IDs across 32 vendor IDs** are recognised — the same set the vendor's own WebHID
  configurator accepts. These pads are sold under dozens of unbranded names; the silicon and the
  protocol are shared.
- **One device is hardware-verified: `0816:246f` (HCY-K006)** — six keys plus a clickable rotary
  encoder, `SIDE-KEYBOARD` / `SDINNOVATION`.
- Everything else gets the **generic fallback**: global lighting (off, mode, brightness, speed,
  colour) works, because it is identical across the family. Per-key operations report that the
  layout is unknown rather than guessing at key indices. `sdcx list` marks these
  `(layout unverified)`.

Good signs you have one of these: a vendor-defined HID interface on usage page `0xFF00`, a
configurator that is a *website* rather than an app, or packaging naming SDCX, SDINNOVATION or
Shenzhen HCY.

Full list, and how "verified" differs from "recognised": **[`docs/DEVICES.md`](docs/DEVICES.md)**.

## Install

```bash
# recommended — isolated, on PATH
pipx install git+https://github.com/parsaj-dev/sdcx-keypad

# or plain pip
pip install git+https://github.com/parsaj-dev/sdcx-keypad

# or from a checkout
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
pip install .

# or no install at all — there are no dependencies to install
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

Or try it without installing: `nix run github:parsaj-dev/sdcx-keypad -- list`.
</details>

## Permissions (read this first)

**This is the number one first-run problem.** The keypad's configuration interface is owned by
root, so a fresh `sdcx light off` will fail with a permission error until you fix that. This is
normal and expected — nothing is broken.

Quick, one-off test (resets when you unplug):

```bash
sdcx list                     # find the hidraw node, e.g. /dev/hidraw4
sudo chmod 666 /dev/hidraw4
```

Permanent fix — a udev rule that tags the vendor configuration interface `uaccess` and grants the
`input` group access:

```bash
sdcx install-udev-rule --print          # read it before you run it
sudo sdcx install-udev-rule             # writes /etc/udev/rules.d/70-sdcx-keypad.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# then unplug and replug the keypad
```

The rule only matches `hidraw` nodes belonging to known keypad USB IDs. Your keyboard interfaces
— the ones that actually type — are untouched, and nothing else on the system gains access.

## Quick start

Eight commands cover almost everything:

```bash
sdcx list                              # is it there, and on which hidraw node
sdcx info                              # firmware, serial, active profile, auto-sleep
sdcx light off                         # kill the RGB (persists across reboots)
sdcx light get                         # what is it doing right now
sdcx light mode breath                 # switch effect, using the firmware's own defaults
sdcx light set --brightness 2 --color '#ff8800'
sdcx light mode custom                 # hand per-key colour control to the host
sdcx key color all '#101010'           # dim everything to a faint glow
```

Every command also takes `--json`, which is what makes it usable from scripts and panels.

## Command reference

Two flags are **global** and go *before* the subcommand:

| flag | meaning |
|---|---|
| `--json` | print a single JSON object on stdout — including on failure, with a non-zero exit code |
| `--device PATH` | use a specific hidraw node; default is the first keypad found |

```bash
sdcx --json light get
sdcx --device /dev/hidraw4 light off
```

### Discovery and inspection

| command | what it does |
|---|---|
| `sdcx list` | connected keypads: hidraw path, USB ID, model, and whether the layout is verified. Exit code 1 if none found. |
| `sdcx info` | firmware version, serial, active profile and layer, auto-sleep time |
| `sdcx modes` | the lighting modes this device's firmware implements, and which fields each honours |
| `sdcx keys` | addressable keys: index, label |
| `sdcx keys --colors` | ...and read each key's current colour back off the device |

### Global lighting

```bash
sdcx light get                  # current mode, brightness, speed, colour
sdcx light off                  # mode 0
sdcx light mode breath          # by name (case-insensitive) or by number
sdcx light mode 2
```

`light mode` reproduces what the vendor UI does: it asks the firmware for its preferred defaults
for that mode and writes those back, so switching effects feels identical to the web app.

`light set` changes individual fields on top of the current state and leaves the rest alone:

```bash
sdcx light set --brightness 4
sdcx light set --mode steady --color '#ff8800'
sdcx light set --speed 1 --direction 0
sdcx light set --palette                     # rainbow palette instead of a single colour
```

| flag | values |
|---|---|
| `--mode` | mode name or number |
| `--brightness` | 0–4 |
| `--speed` | 0–4 |
| `--direction` | 0 or 1 |
| `--color` | `#RRGGBB` (also switches to single-colour mode) |
| `--palette` | switch back to the rainbow palette |

### Per-key colour

```bash
sdcx key color 0 '#00ff00'      # one key, by index
sdcx key color all '#101010'    # every key on the layout
```

Per-key colour is only *visible* in Custom mode (`sdcx light mode custom`). In any other mode the
on-device effect engine repaints the LEDs over your writes and it looks like nothing happened.

Key indices are sparse — on the K006 the six keys are `0`–`5` and the three knob actions are
`16` (press), `17` (counter-clockwise) and `18` (clockwise). `sdcx keys` lists them.

### Device settings

```bash
sdcx profile 0                  # select a configuration scheme (0-based)
sdcx sleep 300                  # auto-sleep after N seconds
sdcx factory-reset --yes        # erases keymap, macros and per-key colours
```

`factory-reset` refuses to run without `--yes`.

### Permissions helper

```bash
sdcx install-udev-rule --print  # print the rule to stdout, write nothing
sudo sdcx install-udev-rule     # write /etc/udev/rules.d/70-sdcx-keypad.rules
```

## Live effects

These run on *your machine*, one frame at a time, pushed to the pad as per-key colours. The
device's built-in effects can't do this, because they know nothing about the host — which is why
a CPU heat map is possible at all.

```bash
sdcx effect list
sdcx effect cpu                                  # CPU load heat map from /proc/stat
sdcx effect rainbow --fps 30
sdcx effect breathe --color '#7c4dff' --restore
sdcx effect chase --duration 10
```

| effect | what it does |
|---|---|
| `solid` | every key the given colour |
| `rainbow` | hue sweep across the pad, animated |
| `breathe` | the given colour pulsing in brightness |
| `chase` | a lit key running through the six main keys |
| `cpu` | heat map of real CPU load from `/proc/stat` |

| flag | default | meaning |
|---|---|---|
| `--fps` | `20.0` | frames per second, clamped to 1–60 |
| `--duration` | `0` | seconds; `0` runs until interrupted |
| `--color` | `#7c4dff` | base colour for `solid`, `breathe`, `chase` |
| `--restore` | off | put the previous lighting state back on exit |

The runner switches the device into Custom mode automatically, and only writes the keys whose
colour actually changed — so a mostly-static frame costs one or two transfers instead of nine.
`Ctrl-C` and `SIGTERM` both stop it cleanly.

Adding your own effect is a single render function in
[`sdcx/effects.py`](sdcx/effects.py): given a frame number, elapsed time and the key list, return
a `{key_index: (r, g, b)}` dict.

## Light modes (HCY-K006)

The ticks are the firmware's own capability flags — which fields it honours in that mode. Other
devices in the family may expose a different set; `sdcx modes` asks yours.

| value | name | zh | brightness | speed | direction | colour | palette |
|---|---|---|---|---|---|---|---|
| 0 | Off | 关闭 | | | | | |
| 1 | Steady | 常亮 | ✓ | | | ✓ | ✓ |
| 2 | Breath | 呼吸 | ✓ | ✓ | | ✓ | ✓ |
| 3 | Press-lit | 按亮 | ✓ | ✓ | | ✓ | ✓ |
| 4 | Tidal | 潮汐 | ✓ | ✓ | | ✓ | ✓ |
| 5 | Custom | custom | ✓ | | | | ✓ |

Mode 5 is the one that hands per-key colour to the host.

## How it works

Alongside its keyboard interfaces, the keypad exposes a **vendor-defined HID interface** on usage
page `0xFF00`, carrying 64-byte reports with report ID 0. On Linux that is a single
`/dev/hidrawN` node and a `read()`/`write()` pair — which is why this package needs no HID
binding, no `libusb`, and no packages at all.

The protocol was not reverse-engineered from USB captures. The vendor ships a WebHID
configurator at `sdcx-tech.com` whose JavaScript bundle contains the whole device API in readable
form: command bytes, field offsets, per-device capability JSON, the accepted USB ID list. It was
read out of the web app and re-implemented. Packet layouts, the firmware quirks the web app works
around, and where each constant came from are written up in
**[`docs/PROTOCOL.md`](docs/PROTOCOL.md)**.

Two details worth knowing if you build on it: device discovery matches on the *report descriptor*
rather than an interface number, so a firmware revision that reorders interfaces won't break it;
and unsolicited `AA FA` lighting notifications from the device are recognised and skipped, so
someone twisting the knob mid-command doesn't corrupt a reply.

## Integrations: panels, widgets, scripts

Every subcommand takes `--json` and answers with one object carrying an `ok` field, errors
included — so you never have to parse human prose. That makes it straightforward to drive from
waybar, eww, polybar, a keybind, a systemd unit, or a plain shell script:
`sdcx --json light get | jq -r .mode_name`. An optional [Quickshell](https://quickshell.org)
overlay widget built on exactly that interface lives in [`quickshell/`](quickshell/) as a worked
example; see [`quickshell/README.md`](quickshell/README.md). It is entirely optional and nothing
in the CLI depends on it.

## Safety

**Firmware update is documented but deliberately not implemented.** Command groups `0x55` and
`0x5A` are the bootloader/flash path. They are described in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) for completeness, and nothing in this package can send
them. A mistake there bricks the device with no recovery short of hardware. Please don't add them
casually — see [CONTRIBUTING.md](CONTRIBUTING.md).

`factory-reset` *is* implemented. It discards your keymap, macros and per-key colours, which is
why it is gated behind `--yes`.

Everything else here writes only to the vendor configuration interface of a device you plugged in
yourself.

## Contributing

New devices, transcribed key layouts and bug reports are all welcome — especially "this works on
my pad, here is the `lsusb` line". See [CONTRIBUTING.md](CONTRIBUTING.md), and use the
[new device report](.github/ISSUE_TEMPLATE/new-device.md) template.

## Licence

MIT. See [LICENSE](LICENSE).
