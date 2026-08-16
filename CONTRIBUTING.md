# Contributing

The most valuable contribution is small: *"my keypad is `xxxx:yyyy`, here is what works."* There
are 196 recognised USB IDs and exactly one that anybody has verified against real hardware, so
almost any report moves the project forward.

## Running from a checkout

No install step and nothing to set up — the package has no dependencies:

```bash
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
python3 -m sdcx list
python3 -m sdcx --json light get
```

Python 3.11+ and Linux (`/dev/hidraw`, `/sys/class/hidraw`). If reads fail with a permission
error, install the udev rule as described in the README — that is expected on a first run, not a
bug.

Nix users: `nix develop` gives a shell with `python3` and `usbutils` and puts the checkout on
`PYTHONPATH`.

There is no test suite. The only meaningful checks need hardware, so please say in your PR what
you actually ran and on which device.

## The no-dependencies rule

**`sdcx` depends on the Python standard library and nothing else. This is a hard constraint, not
an accident.**

The vendor configuration interface is a plain 64-byte hidraw channel — `open()`, `write()`,
`read()`. That is all the protocol needs, so no HID binding, no `libusb`, no `hidapi`, no colour
library. The payoff is that the tool installs anywhere, runs from a checkout with zero setup, can
be dropped into a distro or a Nix closure without dragging a Python environment behind it, and is
small enough to audit before you let it write to your hardware.

A pull request that adds a runtime dependency will be asked to remove it. Build- and
development-time tooling is a separate question and is fine to propose.

## Adding a device layout

Layouts live in [`sdcx/layouts.py`](sdcx/layouts.py). Three frozen dataclasses do the work:

- **`Key`** — one addressable input. `index` is the device's own `key_index`, used to address the
  key in per-key colour writes; it is sparse (on the K006 the six keys are 0–5 and the three knob
  actions are 16, 17, 18). `row`/`col` are the key's *physical* position on the pad, so a UI can
  draw it. `kind` is `"key"` or `"knob"`.
- **`LightMode`** — one entry in the device's lighting mode list: `value`, `name`, `name_zh`, and
  boolean capability flags (`brightness`, `speed`, `direction`, `color`, `palette`) saying which
  fields the firmware honours in that mode.
- **`Layout`** — the device itself: `model`, `vendor_id`, `product_id`, its `keys` and `modes`,
  the matrix dimensions, `mcu_type`, and `verified`.

Register it in the `LAYOUTS` dict, keyed by `(vendor_id, product_id)`. Anything not in that dict
falls back to `generic_layout()`, which exposes the standard mode set and no keys.

### Where the per-device data comes from

The vendor's WebHID app fetches one JSON file per USB ID (for the K006 that is
`0816_246f.json`), describing the lighting modes the firmware implements and the physical
position of every key. A reference copy of the K006 one is in
[`docs/reference-layout-0816_246f.js`](docs/reference-layout-0816_246f.js), and
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) explains the format and where it is served from.

The relevant parts are **transcribed by hand into `layouts.py`**, on purpose: the package must
never need the vendor's site at runtime. So when adding a device, copy the values in — don't add
code that downloads them.

Two transcription traps, both learned the hard way on the K006:

- The JSON's own `row`/`col` are **electrical matrix positions** and do not correspond to where
  the key sits on the board. Derive `row`/`col` for a `Key` from the layout's `x`/`y`
  coordinates instead.
- A rotary encoder appears as several key indices sharing one physical control. Mark them
  `kind="knob"` so a UI can draw them as one thing.

Set `verified=True` only if you have run it against the physical device and watched the right LED
light up. If you transcribed a layout but have no hardware, say so in the PR and leave it
`False`.

### Adding a recognised USB ID

[`sdcx/devices.json`](sdcx/devices.json) is a rendering of the vendor bundle's device filter, not
a hand-maintained list. If your device is missing from it, open an issue with the `lsusb` output
rather than editing the file — it probably means the bundle has been updated and the whole list
should be re-extracted.

## Do not implement the firmware commands

**Command groups `0x55` and `0x5A` — the bootloader and flash path — must not be implemented.**

They are documented in [`docs/PROTOCOL.md` §5](docs/PROTOCOL.md) for completeness, and nothing in
this package can send them. That is a deliberate choice, not an oversight. A mistake in a flash
routine bricks the device with no recovery short of attaching a programmer, and there is no way
to test one safely across a family of 196 near-identical products whose firmware nobody here has
a copy of.

Pull requests adding firmware update, bootloader entry, or anything that writes to those command
groups will be declined. If you have a genuine need, open an issue and describe it first.

## Style

- Standard library only (see above).
- Match the surrounding code: `from __future__ import annotations`, type hints, frozen
  dataclasses for data.
- Comments explain *why* — especially where the firmware does something surprising. Most of the
  existing comments exist because a quirk cost somebody an hour.
- Every CLI subcommand must support `--json` and emit a single object with an `ok` field, errors
  included. Scripts and panel widgets depend on never parsing prose.
- Keep human output terse and copy-pasteable.

## Licence

By contributing you agree your work is released under the MIT licence, as in
[LICENSE](LICENSE).
