# sdcx-keypad

Linux driver and CLI for SDCX / SDINNOVATION USB macropads — turn the RGB off, drive it from scripts, or run host-computed light shows on it. Pure Python standard library, no dependencies.

## Where the protocol came from

The vendor ships a WebHID configurator at `sdcx-tech.com`. Its Next.js bundle contains the entire device API in readable JavaScript — command bytes, field offsets, per-device capability JSON, the lot. No USB capture was needed; the protocol was read out of the web app and re-implemented. The full writeup, including the packet layouts and the firmware quirks the web app works around, is in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

The config channel is a vendor-defined HID interface (usage page `0xFF00`) carrying 64-byte reports with report ID 0. On Linux that is one `/dev/hidrawN` node and a `read()`/`write()` pair — which is why this package needs no HID binding, no `libusb`, and no packages at all. That matters in practice: it has to run from a Quickshell widget on NixOS without dragging in a Python environment.

## Install

```bash
pipx install git+https://github.com/parsaj-dev/sdcx-keypad
# or, from a checkout:
pip install .
# or, with no install at all:
python3 -m sdcx --help
```

Requires Python 3.11+ and Linux (`/dev/hidraw` and `/sys/class/hidraw`).

Nix users: the flake provides `packages.default` and a `nixosModules.default` that installs the tool system-wide and ships the udev rule.

## Quickstart

The thing most people want:

```bash
sdcx light off
```

That writes one 64-byte report and the keypad stores it in flash — it survives unplugging and rebooting. The keys keep working; only the LEDs go dark.

## Permissions

The vendor interface is root-only by default. One-off:

```bash
sudo chmod 666 /dev/hidrawN     # find N with: sdcx list
```

Permanent — a udev rule matching the vendor config interface, tagging it `uaccess` and giving the `input` group access:

```bash
sdcx install-udev-rule --print   # read it before you run it
sudo sdcx install-udev-rule
sudo udevadm control --reload-rules && sudo udevadm trigger
# then replug the keypad
```

The rule only ever matches `hidraw` nodes for known keypad USB IDs. The keyboard interfaces are untouched.

## Command tour

Every subcommand takes `--json` (a single JSON object on stdout, including on failure, with a non-zero exit code) and `--device PATH` (pick a specific hidraw node; the default is the first one found). Both are global flags and go before the subcommand.

### Discovery

```bash
sdcx list                 # connected keypads, one per line: path, USB id, model
sdcx info                 # firmware, serial, active profile, layer, auto-sleep
sdcx modes                # lighting modes this device's firmware implements
sdcx keys                 # addressable keys: index, label
sdcx keys --colors        # ...and read each key's current colour off the device
```

### Global lighting

```bash
sdcx light get                       # current mode, brightness, speed, colour
sdcx light off                       # mode 0
sdcx light mode breath               # by name (case-insensitive) or by number
sdcx light mode 2
```

`light mode` reproduces what the vendor UI does: it asks the firmware for its preferred defaults for that mode and writes those back, so switching effects feels identical to the web app.

`light set` changes individual fields on top of the current state, leaving the rest alone:

```bash
sdcx light set --brightness 4
sdcx light set --mode steady --color '#ff8800'
sdcx light set --speed 1 --direction 0
sdcx light set --palette              # rainbow palette instead of a single colour
```

| flag | values |
|---|---|
| `--mode` | mode name or number |
| `--brightness` | 0–4 |
| `--speed` | 0–4 |
| `--direction` | 0 or 1 |
| `--color` | `#RRGGBB` (sets single-colour mode) |
| `--palette` | switch back to the rainbow palette |

### Per-key colour

```bash
sdcx key color 0 '#00ff00'
sdcx key color all '#101010'
```

Per-key colour is only *visible* in Custom mode (`sdcx light mode custom`) — in any other mode the on-device effect engine repaints the LEDs over your writes.

### Host-driven effects

These run on your machine, one frame at a time, pushed as per-key colours. The device's own effects can't do this because they know nothing about the host.

```bash
sdcx effect list
sdcx effect cpu                                  # CPU load heat map from /proc/stat
sdcx effect rainbow --fps 30
sdcx effect breathe --color '#7c4dff' --restore
sdcx effect chase --duration 10
```

| flag | default | meaning |
|---|---|---|
| `--fps` | `20.0` | frames per second, capped at 60 |
| `--duration` | `0` | seconds; `0` runs until Ctrl-C |
| `--color` | `#7c4dff` | base colour for `solid`, `breathe`, `chase` |
| `--restore` | off | put the previous lighting state back on exit |

| effect | what it does |
|---|---|
| `solid` | every key the given colour |
| `rainbow` | hue sweep across the pad, animated |
| `breathe` | the given colour pulsing in brightness |
| `chase` | a lit key running through the six main keys |
| `cpu` | heat map of real CPU load from `/proc/stat` |

The runner switches the device to Custom mode automatically and only writes the keys whose colour actually changed, so a mostly-static frame costs one or two transfers instead of nine.

### Device settings

```bash
sdcx profile 0            # select a configuration scheme (0-based)
sdcx sleep 300            # auto-sleep after N seconds
sdcx factory-reset --yes  # erases keymap, macros and per-key colours
```

`factory-reset` refuses to run without `--yes`.

## Why not just use the vendor web app

| | vendor WebHID app | `sdcx` |
|---|---|---|
| live effects driven by host state (CPU load, notifications, anything scriptable) | no | yes |
| usable from a script, a keybind, a widget, a systemd unit | no | yes — and `--json` on every command |
| works headless / over SSH | no | yes |
| needs a browser with WebHID (Chromium-family) | yes | no |
| offline, auditable, no vendor site | no | yes |
| documented protocol | no | [`docs/PROTOCOL.md`](docs/PROTOCOL.md) |

The web app is a fine configurator. It just can't be part of anything else on your machine.

## Features

| | |
|---|---|
| discovery | matches on the report descriptor, not an interface number, so a firmware revision reordering interfaces won't break it |
| global lighting | read and write mode, brightness, speed, direction, HSV colour, palette |
| per-key RGB | read and write individual key colours |
| host effects | five built in, extensible in `sdcx/effects.py` |
| device info | firmware version, serial, profile/layer counts, auto-sleep |
| profiles | select the active configuration scheme |
| JSON output | on every command, errors included — this is the backend for the Quickshell widget |
| async events | unsolicited `AA FA` lighting notifications are recognised and skipped, so on-device changes don't corrupt a reply |
| dependencies | none |

## Light modes (HCY-K006)

The booleans are the firmware's own capability flags — which fields it honours in that mode.

| value | name | zh | brightness | speed | direction | colour | palette |
|---|---|---|---|---|---|---|---|
| 0 | Off | 关闭 | | | | | |
| 1 | Steady | 常亮 | ✓ | | | ✓ | ✓ |
| 2 | Breath | 呼吸 | ✓ | ✓ | | ✓ | ✓ |
| 3 | Press-lit | 按亮 | ✓ | ✓ | | ✓ | ✓ |
| 4 | Tidal | 潮汐 | ✓ | ✓ | | ✓ | ✓ |
| 5 | Custom | custom | ✓ | | | | ✓ |

Mode 5 is the one that hands per-key colour to the host.

## Supported devices

The vendor bundle accepts **196 USB IDs across 32 vendor IDs**, all on usage page `0xFF00` / usage `0x02`; the full list is in [`sdcx/devices.json`](sdcx/devices.json). The protocol is shared across the family — what differs per device is the key layout and which light modes the firmware implements.

Hardware-verified on exactly one:

- **HCY-K006** — `0816:246f`, product string `SIDE-KEYBOARD`, manufacturer `SDINNOVATION`, MCU `951`. Six keys plus a clickable rotary encoder. Sold by Shenzhen HCY (szhcykb.com).

Everything else is recognised and gets global lighting, which is identical across the family; per-key operations report that the layout is unknown rather than guessing at indices. `sdcx list` marks unverified layouts. If you have one, a transcribed layout in `sdcx/layouts.py` is a welcome PR.

## Safety

**Firmware update is documented but not implemented, on purpose.** Command groups `0x55` and `0x5A` are the bootloader/flash path. They are written up in [`docs/PROTOCOL.md` §5](docs/PROTOCOL.md) for completeness, and nothing in this package can send them. A mistake there bricks the device with no recovery short of hardware. Don't add them casually.

`factory-reset` *is* implemented — it discards your keymap, macros and colours, so it is gated behind `--yes`.

## Development

```bash
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
python3 -m sdcx list        # no install step needed
```

The recognised-device list lives at `sdcx/devices.json`, inside the package, so it travels with a wheel; `docs/PROTOCOL.md` documents where it came from.

## Licence

MIT. See [LICENSE](LICENSE).
