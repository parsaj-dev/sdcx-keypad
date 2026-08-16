# Contributing

The most valuable contribution is small: a report of the form "my keypad is `xxxx:yyyy`, here is
what works." There are 196 recognised USB IDs and exactly one that has been verified against real
hardware, so almost any report moves the project forward.

## Running from a checkout

There is no install step and nothing to set up; the package has no dependencies.

```bash
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
python3 -m sdcx list
python3 -m sdcx --json light get
```

Requirements: Python 3.11+ and Linux (`/dev/hidraw`, `/sys/class/hidraw`). If reads fail with a
permission error, install the udev rule as described in the README; that is expected on a first
run, not a bug.

Nix users: `nix develop` gives a shell with `python3` and `usbutils`, and puts the checkout on
`PYTHONPATH`.

There is no test suite. The only meaningful checks need hardware, so state in the pull request
what was run and on which device.

## The no-dependencies rule

`sdcx` depends on the Python standard library and nothing else. This is a hard constraint, not an
accident.

The vendor configuration interface is a plain 64-byte hidraw channel: `open()`, `write()`,
`read()`. That is all the protocol needs, so no HID binding, no `libusb`, no `hidapi`, and no
colour library are required. The payoff is that the tool installs anywhere, runs from a checkout
with zero setup, can be dropped into a distro or a Nix closure without dragging a Python
environment behind it, and is small enough to audit before it is allowed to write to hardware.

A pull request that adds a runtime dependency will be asked to remove it. Build- and
development-time tooling is a separate question and is fine to propose.

## Adding a device layout

Layouts live in [`sdcx/layouts.py`](sdcx/layouts.py). Three frozen dataclasses do the work:

- `Key`: one addressable input. `index` is the device's own `key_index`, used to address the key
  in per-key colour writes; it is sparse (on the K006 the six keys are 0-5 and the three knob
  actions are 16, 17, 18). `row`/`col` are the key's physical position on the pad, for a UI to
  draw it. `kind` is `"key"` or `"knob"`.
- `LightMode`: one entry in the device's lighting mode list: `value`, `name`, `name_zh`, and
  boolean capability flags (`brightness`, `speed`, `direction`, `color`, `palette`) stating which
  fields the firmware honours in that mode.
- `Layout`: the device itself: `model`, `vendor_id`, `product_id`, its `keys` and `modes`, the
  matrix dimensions, `mcu_type`, and `verified`.

Register a new layout in the `LAYOUTS` dict, keyed by `(vendor_id, product_id)`. Anything not in
that dict falls back to `generic_layout()`, which exposes the standard mode set and no keys.

### Where the per-device data comes from

The vendor's WebHID app fetches one JSON file per USB ID (for the K006 that is
`0816_246f.json`), describing the lighting modes the firmware implements and the physical
position of every key. A reference copy of the K006 file is in
[`docs/reference-layout-0816_246f.js`](docs/reference-layout-0816_246f.js), and
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) explains the format and where it is served from.

The relevant parts are transcribed by hand into `layouts.py`, deliberately: the package must
never need the vendor's site at runtime. When adding a device, copy the values in; do not add
code that downloads them.

Two transcription traps, both encountered while adding the K006:

- The JSON's own `row`/`col` are electrical matrix positions and do not correspond to where the
  key sits on the board. Derive `row`/`col` for a `Key` from the layout's `x`/`y` coordinates
  instead.
- A rotary encoder appears as several key indices sharing one physical control. Mark them
  `kind="knob"` so a UI can draw them as one thing.

Set `verified=True` only if the layout has been run against the physical device and the right LED
was observed to light up. If a layout is transcribed without hardware to test it against, say so
in the pull request and leave it `False`.

### Adding a recognised USB ID

[`sdcx/devices.json`](sdcx/devices.json) is a rendering of the vendor bundle's device filter, not
a hand-maintained list. If a device is missing from it, open an issue with the `lsusb` output
rather than editing the file; that most likely means the bundle has been updated and the whole
list should be re-extracted.

## Do not implement the firmware update commands

Command groups `0x55` and `0x5A`, the bootloader and flash path, must not be implemented.

They are documented in [`docs/PROTOCOL.md` §5](docs/PROTOCOL.md) for completeness, and nothing in
this package can send them. That is a deliberate choice, not an oversight. A mistake in a flash
routine bricks the device with no recovery short of attaching a programmer, and there is no way
to test one safely across a family of 196 near-identical products whose firmware nobody
maintaining this project has a copy of.

Pull requests adding firmware update, bootloader entry, or anything that writes to those command
groups will be declined. For a genuine need, open an issue describing it first.

## Style

- Standard library only (see above).
- Match the surrounding code: `from __future__ import annotations`, type hints, frozen
  dataclasses for data.
- Comments explain why, especially where the firmware does something surprising. Most of the
  existing comments exist because a quirk cost someone an hour.
- Every CLI subcommand must support `--json` and emit a single object with an `ok` field, errors
  included. Scripts and panel widgets depend on never parsing prose.
- Keep human output terse and copy-pasteable.

## Licence

By contributing, you agree that your work is released under the MIT licence, as in
[LICENSE](LICENSE).
