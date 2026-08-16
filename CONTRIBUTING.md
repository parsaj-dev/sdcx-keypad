# Contributing

Most contributions here take two minutes and need nothing but the keypad already
on the desk. You do not need to know the USB protocol, read the firmware, or set
anything up: there are 196 recognised USB IDs and only one that has been
verified against real hardware, so a short report from anyone else's keypad is
genuinely useful. Pick whatever below matches the time you have.

## Report your keypad (two minutes, no setup)

This is the single most valuable thing anyone can send this project, and it
just got a lot easier: `sdcx` now has a `report` subcommand that collects
everything needed in one read-only pass and prints a markdown block ready to
paste into an issue.

```bash
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
python3 -m sdcx report
```

Then open a [new device issue](../../issues/new?template=new-device.md) and
paste the output in. That is the whole contribution.

`report` only reads from the device: it does not change any setting, colour, or
mode. If you would rather install than run from a checkout, see
[README.md](README.md) first.

## Other easy contributions

| what | first step |
|---|---|
| Fix or clarify documentation | Docs live in [`docs/`](docs) and in the top-level `.md` files. A typo fix or a clearer sentence is a welcome pull request on its own. |
| Add a keycode name | Keycode tables live in `sdcx/keycodes.py`. If `sdcx keycodes` is missing one your keyboard layout needs, add it there. |
| Report something that does not work | Open an issue describing what you ran and what happened. Exact error text is more useful than a paraphrase. |
| Test an untested code path | `keymap set` and `macro set` have never been run against real hardware. Trying either on your device and reporting the result (worked, or the exact failure) is a real and valuable contribution, not just a formality. |

## Adding a device layout

This is a medium-effort contribution: no code changes to the effect engine or
CLI, just describing a new device so `sdcx` recognises it fully instead of
falling back to the generic layout.

Layouts live in [`sdcx/layouts.py`](sdcx/layouts.py) and are built from three
frozen dataclasses:

- **`Key`**: one addressable input. `index` is the device's own `key_index`,
  used to address the key in per-key colour writes; it is sparse (on the K006
  the six keys are 0-5 and the three knob actions are 16, 17, 18). `row`/`col`
  are the key's physical position on the pad, for a UI to draw it. `kind` is
  `"key"` or `"knob"`.
- **`LightMode`**: one entry in the device's lighting mode list: `value`,
  `name`, `name_zh`, and boolean capability flags (`brightness`, `speed`,
  `direction`, `color`, `palette`) stating which fields the firmware honours in
  that mode.
- **`Layout`**: the device itself: `model`, `vendor_id`, `product_id`, its
  `keys` and `modes`, the matrix dimensions, `mcu_type`, and `verified`.

Register the new layout in the `LAYOUTS` dict, keyed by `(vendor_id,
product_id)`. Anything not in that dict falls back to `generic_layout()`, which
exposes the standard mode set and no keys, so adding a real layout is a
genuine improvement even without hardware verification.

### Where the per-device data comes from

The vendor's WebHID app fetches one JSON file per USB ID (for the K006 that is
`0816_246f.json`), describing the lighting modes the firmware implements and
the physical position of every key. A reference copy of the K006 file is in
[`docs/reference-layout-0816_246f.js`](docs/reference-layout-0816_246f.js), and
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) explains the format and where it is
served from.

The relevant parts are transcribed by hand into `layouts.py`, deliberately: the
package must never need the vendor's site at runtime. When adding a device,
copy the values in rather than adding code that downloads them.

Two tips that will save time, both learned while adding the K006:

- The JSON's own `row`/`col` are electrical matrix positions and do not
  correspond to where the key actually sits on the board. Derive `row`/`col`
  for a `Key` from the layout's `x`/`y` coordinates instead.
- A rotary encoder appears in the JSON as several key indices sharing one
  physical control. Mark them `kind="knob"` so a UI can draw them as one
  thing.

Set `verified=True` only once the layout has actually been run against the
physical device and the right LED was observed to light up. There is no shame
in leaving it `False`: a transcribed-but-unverified layout is still much
better than the generic fallback. Just say in the pull request that it has not
been tested on hardware.

### Adding a recognised USB ID

[`sdcx/devices.json`](sdcx/devices.json) is a rendering of the vendor bundle's
device filter, not a hand-maintained list. If a device is missing from it,
open an issue with the `lsusb` output rather than editing the file; that most
likely means the bundle has been updated and the whole list should be
re-extracted.

## Adding an effect

This is a good first code contribution: the effect system is designed so that
a new effect is mostly declarative, and existing effects in
[`sdcx/effects.py`](sdcx/effects.py) are the best reference.

An effect is an `Effect` dataclass instance:

```python
Effect(
    "name", "short description", render_function,
    help="longer help text shown by --help",
    params=_params("color", "speed", "intensity"),
)
```

The pieces:

- **A render function**, matching the signature
  `(frame_index: int, elapsed_seconds: float, keys: tuple[Key, ...], params: EffectParams) -> Frame`,
  where `Frame` is `dict[key_index, (r, g, b)]`. It is called once per frame and
  returns the colour for every key it wants lit.
- **`PARAM_LIBRARY`**, a shared dictionary of named parameters (`color`,
  `speed`, `intensity`, `palette`, and so on). An effect declares which ones it
  uses by name via the `_params(...)` helper; it does not define its own flags.
  Reusing an existing name automatically gets the effect the matching CLI flag,
  JSON manifest entry, and default, so the render function stays focused on the
  actual animation.
- **Registering the effect** in the `EFFECTS` dict at the bottom of the file,
  keyed by the name used on the command line (`sdcx effect <name>`).

If an effect needs a genuinely new kind of parameter, add it to
`PARAM_LIBRARY` first; two effects that both take a `speed` should mean the
same thing by it.

## Development setup

There is no install step and nothing to set up beyond a checkout; the package
has no runtime dependencies (more on why below).

```bash
git clone https://github.com/parsaj-dev/sdcx-keypad
cd sdcx-keypad
python3 -m sdcx list
python3 -m sdcx --json light get
```

Requirements: Python 3.11+ and Linux (`/dev/hidraw`, `/sys/class/hidraw`). If
reads fail with a permission error, install the udev rule as described in the
README; that is expected on a first run, not a bug.

Nix users: `nix develop` gives a shell with `python3` and `usbutils`, and puts
the checkout on `PYTHONPATH`.

Run the self-test suite before sending a pull request:

```bash
python3 -m sdcx._selftest
```

It covers 27 tests and needs no hardware. There is no automated coverage for
hardware behaviour itself, since that needs a physical device; state in the
pull request what was tested and on which device.

### Conventions

- Every CLI subcommand must support `--json` and emit a single object with an
  `ok` field, errors included. Scripts and panel widgets depend on never
  parsing prose.
- Match the surrounding code: `from __future__ import annotations`, type
  hints, frozen dataclasses for data.
- Comments explain why, especially where the firmware does something
  surprising. Most of the existing comments exist because a quirk cost someone
  an hour.
- Keep human output terse and copy-pasteable.

## Licence

By contributing, you agree that your work is released under the MIT licence,
as in [LICENSE](LICENSE).

## Project constraints

<details>
<summary>Two things this project deliberately does not do, and why</summary>

These are not arbitrary rules; they follow from what the device is and what
this package promises to be. Both are still enforced: a pull request that
crosses either line will be asked to change, not just discussed.

### No runtime dependencies

`sdcx` depends on the Python standard library and nothing else.

The vendor configuration interface is a plain 64-byte hidraw channel:
`open()`, `write()`, `read()`. That is all the protocol needs, so no HID
binding, no `libusb`, and no colour library are required. The payoff is that
the tool installs anywhere, runs from a checkout with zero setup, can be
dropped into a distro or a Nix closure without dragging a Python environment
behind it, and is small enough to audit before it is trusted to write to
hardware.

A pull request that adds a runtime dependency will be asked to remove it.
Build- and development-time tooling is a separate question and is fine to
propose.

### No firmware update commands

Command groups `0x55` and `0x5A`, the bootloader and flash path, are not
implemented, and pull requests adding firmware update, bootloader entry, or
anything that writes to those command groups will be declined.

They are documented in [`docs/PROTOCOL.md` §5](docs/PROTOCOL.md) for
completeness, because understanding the protocol is useful even where this
package refuses to act on it. A mistake in a flash routine bricks the device
with no recovery short of attaching a programmer, and there is no way to test
one safely across a family of 196 near-identical products whose firmware
nobody maintaining this project has a copy of. If there is a genuine need,
open an issue describing it first.

</details>
