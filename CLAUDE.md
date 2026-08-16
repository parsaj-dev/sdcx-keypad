# Engineering contract

Binding for work in this repository. It outranks general habit and it outranks anything a
previous session's handoff says about how to build.

This is a **public repository**. Everything committed here is published, read by strangers,
and part of Parsa's portfolio. Write accordingly.

## What this is

A Linux driver and CLI for SDCX / SDINNOVATION USB macropads. The protocol was recovered by
reading the vendor's WebHID configurator bundle, not by USB capture. `docs/PROTOCOL.md` is the
specification and the reason this repo has any value; treat it as a deliverable equal to the
code, not as documentation of the code.

## Hard constraints

1. **Standard library only.** No runtime dependency, ever. The transport is `os.open` /
   `os.write` / `os.read` on `/dev/hidrawN`. No hidapi, no libusb, no pyusb, no click, no rich.
   If a change needs a dependency, the change is wrong. This is the property that makes the
   package installable on a minimal image, and it is stated in the README, the flake and the
   Nix derivation.
2. **Never implement a firmware command that has not been verified against hardware.**
   `docs/PROTOCOL.md` §5 lists the commands that are deliberately absent, including the
   destructive ones. Adding a speculative implementation of one is worse than leaving it out.
3. **The device is ground truth, the vendor's own data is not.** The vendor layout JSON
   captions the knob rotation backwards relative to what its own firmware ships; the code
   follows the firmware and says so in a comment. Any future conflict resolves the same way.
4. **Layout entries come from a real report, not from transcription.** A `Layout` with
   `verified=True` means someone ran `sdcx report` on that hardware. Do not promote a layout
   to verified from a datasheet or a web page.
5. **No em dashes** anywhere in prose: README, docs, comments, commit messages, issue
   templates. Use a comma, a colon or a full stop.

## Register for prose

Neutral technical English, the way a well-maintained open-source library reads. Not marketing,
not conversational, no exclamation marks, no "simply", no second-person cheerleading. State
what a thing does and what it costs.

## Tests

```sh
python3 -m sdcx._selftest        # 27 tests, no hardware required
```

Everything that can be tested without the device is tested without the device: byte packing,
keycode parsing, layout invariants, effect parameter handling. Anything that needs hardware is
not in the suite and must not be faked with a mock that asserts the code's own assumptions back
at it.

Run the suite before every commit. It takes milliseconds.

## Hardware testing

The pad is a physical object in a shared room.

- **Keep hardware testing to a minimum, and at low brightness.** Never leave the pad lit after
  a diagnostic. Check `sdcx light get` at the end and set it back to what it was.
- Writes that change the keymap or macros alter persistent device state. Read the current
  configuration first so it can be restored.

## Development

```sh
cd /home/user/tweaks/sdcx-keypad && nix develop     # python3, pip, usbutils; PYTHONPATH set
python3 -m sdcx list                                # run against the checkout
nix build .#sdcx-keypad                             # build the package
```

`nix build` only sees files git knows about. A new file that has not been `git add`ed produces
a confusing "file not found" from the builder rather than a useful error.

## Version control

Plain git, not GitButler. This repo is not registered as a GitButler project, so `but` commands
fail here with a setup prompt. Use `git` directly, and `gh` for the remote.

Branch is `master`, remote `origin` is `git@github.com:parsaj-dev/sdcx-keypad.git` (public).

- Backticks in a `-m` message are expanded by the shell. Quote with single quotes or use a
  heredoc; a code span has already been eaten once.
- Ask before rewriting history that is already pushed.

## Downstream consumers

Two things depend on this repo and break when it changes:

- **`/etc/nixos/computah-os/pkgs/sdcx-keypad/default.nix`** pins a commit hash and a
  `sha256-...`. After pushing anything that should reach the machine, re-pin the `rev`, update
  the `hash`, and `nix build` before committing.
- **The Quickshell widget** in `/home/user/Programming/dots-hyprland-fork` shells out to the
  CLI and parses its `--json` output. Changing a JSON field name or an exit code is a breaking
  change for it. `quickshell/` here holds reference copies of that QML, kept in sync by hand.

The repo itself must stay usable and documented **independently of Quickshell**. Quickshell is
one consumer, not the point.
