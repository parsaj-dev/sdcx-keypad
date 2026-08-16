"""Command line interface.

Every subcommand accepts --json and prints a single JSON object on stdout, so
this doubles as the backend for the Quickshell widget. Errors also go out as
JSON when --json is set, with a non-zero exit code, so a caller never has to
parse human prose to find out what went wrong.
"""

from __future__ import annotations

import argparse
import errno
import json
import sys
from pathlib import Path

from .device import DeviceNotFound, PermissionDenied, SdcxError, enumerate_devices
from .keycodes import CATEGORIES, REGISTRY, by_category, parse_keycode, search
from .layouts import get_layout, supported_ids
from .protocol import (
    MACRO_SLOTS,
    MAX_BRIGHTNESS,
    MAX_SPEED,
    Keypad,
    LightConfig,
    Macro,
    macro_from_sequence,
    parse_hex_color,
)

UDEV_RULE_PATH = "/etc/udev/rules.d/70-sdcx-keypad.rules"


def _udev_rule() -> str:
    lines = [
        "# SDCX / SDINNOVATION programmable keypads — vendor config interface.",
        "# Grants the console user access to the HID interface on usage page 0xFF00,",
        "# which carries configuration only. The keyboard interfaces are untouched.",
        "# Installed by: sudo sdcx install-udev-rule",
        "",
    ]
    for vid, pid in supported_ids():
        lines.append(
            f'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", '
            f'ATTRS{{idVendor}}=="{vid:04x}", ATTRS{{idProduct}}=="{pid:04x}", '
            f'TAG+="uaccess", MODE="0660", GROUP="input"'
        )
    return "\n".join(lines) + "\n"


def _emit(payload: dict, as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(payload, indent=None if payload.get("_compact") else 2))
    elif human is not None:
        print(human)


def _device_dict(info, layout) -> dict:
    return {
        "path": info.path,
        "usb_id": info.usb_id,
        "vendor_id": f"0x{info.vendor_id:04x}",
        "product_id": f"0x{info.product_id:04x}",
        "name": info.name,
        "model": layout.model,
        "verified": layout.verified,
        "key_count": layout.key_count,
    }


# -- subcommands -----------------------------------------------------------


def cmd_list(args) -> int:
    devices = enumerate_devices()
    payload = {
        "ok": True,
        "devices": [_device_dict(d, get_layout(d.vendor_id, d.product_id)) for d in devices],
    }
    if args.json:
        _emit(payload, True)
    elif not devices:
        print("No supported keypad found.")
        print("If one is plugged in, it may be a USB ID this driver does not know yet.")
    else:
        for d in payload["devices"]:
            mark = "" if d["verified"] else "  (layout unverified)"
            print(f"{d['path']}  {d['usb_id']}  {d['model']}{mark}")
    return 0 if devices else 1


def cmd_info(args) -> int:
    with Keypad.open(path=args.device) as pad:
        config = pad.get_keyboard_config()
        payload = {
            "ok": True,
            "device": _device_dict(pad.info, pad.layout),
            "config": config.to_dict(),
        }
        if args.json:
            _emit(payload, True)
        else:
            print(f"{pad.layout.model}  {pad.info.usb_id}  at {pad.info.path}")
            print(f"  firmware      {config.firmware}")
            print(f"  serial        {config.serial or '-'}")
            print(f"  profile       {config.profile + 1} of {config.profile_count}")
            print(f"  layer         {config.layer + 1} of {config.layer_count}")
            print(f"  auto sleep    {config.auto_sleep_time}s")
    return 0


def cmd_modes(args) -> int:
    layout = None
    devices = enumerate_devices()
    if devices:
        layout = get_layout(devices[0].vendor_id, devices[0].product_id)
    else:
        layout = get_layout(0x0816, 0x246F)
    modes = [
        {
            "value": m.value,
            "name": m.name,
            "name_zh": m.name_zh,
            "brightness": m.brightness,
            "speed": m.speed,
            "direction": m.direction,
            "color": m.color,
            "palette": m.palette,
        }
        for m in layout.modes
    ]
    if args.json:
        _emit({"ok": True, "modes": modes}, True)
    else:
        for m in modes:
            fields = [k for k in ("brightness", "speed", "direction", "color") if m[k]]
            print(f"{m['value']}  {m['name']:<10} {' '.join(fields)}")
    return 0


def cmd_keys(args) -> int:
    with Keypad.open(path=args.device) as pad:
        colors = pad.get_key_colors() if args.colors else {}
        keys = [
            {
                "index": k.index,
                "label": k.label,
                "row": k.row,
                "col": k.col,
                "kind": k.kind,
                **(
                    {"color": "#%02x%02x%02x" % colors[k.index]}
                    if k.index in colors
                    else {}
                ),
            }
            for k in pad.layout.keys
        ]
        if args.json:
            _emit({"ok": True, "model": pad.layout.model, "keys": keys}, True)
        else:
            for k in keys:
                print(f"{k['index']:>3}  {k['label']:<12} {k.get('color', '')}")
    return 0


def cmd_light_get(args) -> int:
    with Keypad.open(path=args.device) as pad:
        light = pad.get_light()
        mode = pad.layout.mode_by_value(light.mode)
        payload = {
            "ok": True,
            "light": light.to_dict(),
            "mode_name": mode.name if mode else f"mode {light.mode}",
            "hex": light.hex,
            "max_brightness": MAX_BRIGHTNESS,
            "max_speed": MAX_SPEED,
        }
        if args.json:
            _emit(payload, True)
        else:
            print(f"mode        {payload['mode_name']} ({light.mode})")
            print(f"brightness  {light.brightness}/{MAX_BRIGHTNESS}")
            print(f"speed       {light.speed}/{MAX_SPEED}")
            print(f"colour      {light.hex}  (h={light.h} s={light.s} v={light.v})")
            print(f"single      {'yes' if light.color else 'no (palette)'}")
    return 0


def cmd_light_off(args) -> int:
    with Keypad.open(path=args.device) as pad:
        pad.off()
    _emit({"ok": True, "mode": 0}, args.json, "Lights off. The setting is saved in the keypad.")
    return 0


def cmd_light_mode(args) -> int:
    with Keypad.open(path=args.device) as pad:
        target = args.mode
        mode = None
        if target.isdigit():
            mode = pad.layout.mode_by_value(int(target))
        if mode is None:
            mode = pad.layout.mode_by_name(target)
        if mode is None:
            names = ", ".join(m.name for m in pad.layout.modes)
            raise SdcxError(f"unknown mode {target!r}. Available: {names}")
        light = pad.set_light_mode(mode.value)
        _emit(
            {"ok": True, "light": light.to_dict(), "mode_name": mode.name},
            args.json,
            f"Mode set to {mode.name}.",
        )
    return 0


def cmd_light_set(args) -> int:
    with Keypad.open(path=args.device) as pad:
        light = pad.get_light()
        if args.mode is not None:
            mode = pad.layout.mode_by_name(args.mode) if not args.mode.isdigit() else pad.layout.mode_by_value(int(args.mode))
            if mode is None:
                raise SdcxError(f"unknown mode {args.mode!r}")
            light.mode = mode.value
        if args.brightness is not None:
            light.brightness = args.brightness
        if args.speed is not None:
            light.speed = args.speed
        if args.direction is not None:
            light.direction = args.direction
        if args.color is not None:
            r, g, b = parse_hex_color(args.color)
            import colorsys

            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            light.h, light.s, light.v = round(h * 360), round(s * 100), round(v * 100)
            light.color = 1
        if args.palette:
            light.color = 0
        pad.set_light(light)
        _emit({"ok": True, "light": light.to_dict()}, args.json, "Applied.")
    return 0


def cmd_key_color(args) -> int:
    with Keypad.open(path=args.device) as pad:
        rgb = parse_hex_color(args.color)
        if args.index == "all":
            targets = {k.index: rgb for k in pad.layout.keys}
            pad.set_key_colors(targets)
        else:
            index = int(args.index)
            if pad.layout.keys and pad.layout.key_by_index(index) is None:
                valid = ", ".join(str(k.index) for k in pad.layout.keys)
                raise SdcxError(f"key index {index} not on this device. Valid: {valid}")
            pad.set_key_color(index, rgb)
        _emit(
            {"ok": True, "index": args.index, "color": "#%02x%02x%02x" % rgb},
            args.json,
            "Set. Note per-key colour is only visible in Custom mode "
            "(sdcx light mode custom).",
        )
    return 0


def cmd_keycodes(args) -> int:
    codes = REGISTRY
    if args.category:
        if args.category not in CATEGORIES:
            raise SdcxError(
                f"unknown category {args.category!r}. Available: " + ", ".join(CATEGORIES)
            )
        codes = tuple(by_category(args.category))
    if args.search:
        wanted = {id(c) for c in search(args.search)}
        codes = tuple(c for c in codes if id(c) in wanted)
    payload = {"ok": True, "keycodes": [c.to_dict() for c in codes]}
    if args.json:
        _emit(payload, True)
    else:
        for c in codes:
            print(f"{c.name:<24} {c.category:<9} {c.code}")
    return 0


def cmd_keymap_get(args) -> int:
    with Keypad.open(path=args.device) as pad:
        keymap = pad.get_keymap(args.layer)
        rows = [
            {
                "label": (k.label if (k := pad.layout.key_by_index(index)) else str(index)),
                **assignment.to_dict(),
            }
            for index, assignment in sorted(keymap.items())
        ]
        payload = {"ok": True, "layer": args.layer, "keys": rows}
        if args.json:
            _emit(payload, True)
        else:
            for row in rows:
                print(f"{row['key_index']:>3}  {row['label']:<12} {row['name']}")
    return 0


def cmd_keymap_set(args) -> int:
    with Keypad.open(path=args.device) as pad:
        assignment = pad.set_key(args.index, parse_keycode(args.keycode), args.layer)
        _emit(
            {"ok": True, "layer": args.layer, "key": assignment.to_dict()},
            args.json,
            f"Key {args.index} is now {assignment.name}.",
        )
    return 0


def cmd_keymap_reset(args) -> int:
    with Keypad.open(path=args.device) as pad:
        defaults = pad.reset_keymap(args.layer)
        _emit(
            {
                "ok": True,
                "layer": args.layer,
                "keys": [a.to_dict() for a in sorted(defaults.values(), key=lambda a: a.key_index)],
            },
            args.json,
            f"Layer {args.layer} restored to the firmware's own key table. "
            "Macros and colours were not touched.",
        )
    return 0


def cmd_macro_get(args) -> int:
    with Keypad.open(path=args.device) as pad:
        if args.raw:
            blob = pad.get_macro_data()
            _emit(
                {"ok": True, "bytes": list(blob)},
                args.json,
                blob.hex(),
            )
            return 0
        macros = [m for m in pad.get_macros() if m.steps or args.all]
        payload = {"ok": True, "macros": [m.to_dict() for m in macros]}
        if args.json:
            _emit(payload, True)
        elif not macros:
            print("No macros stored. Record one with: sdcx macro set 0 'ctrl+c, a'")
        else:
            for macro in macros:
                print(f"macro:{macro.slot}  {len(macro.steps)} steps")
                for step in macro.steps:
                    print(
                        f"    {step.kind_name:<7} {step.code:>3} "
                        f"{'press' if step.press else 'release':<8} {step.delay}ms"
                    )
    return 0


def cmd_macro_set(args) -> int:
    steps = macro_from_sequence(args.sequence, args.delay)
    with Keypad.open(path=args.device) as pad:
        macros = pad.get_macros()
        macros[args.slot] = Macro(args.slot, steps)
        pad.set_macros(macros)
        _emit(
            {"ok": True, "macro": macros[args.slot].to_dict()},
            args.json,
            f"macro:{args.slot} set, {len(steps)} steps. "
            f"Bind it with: sdcx keymap set <key> macro:{args.slot}",
        )
    return 0


def cmd_macro_reset(args) -> int:
    with Keypad.open(path=args.device) as pad:
        pad.reset_macros()
        _emit({"ok": True}, args.json, "Macro area cleared. The keymap was not touched.")
    return 0


def cmd_profile(args) -> int:
    with Keypad.open(path=args.device) as pad:
        pad.set_profile(args.index)
        _emit({"ok": True, "profile": args.index}, args.json, f"Profile {args.index + 1} active.")
    return 0


def cmd_sleep(args) -> int:
    with Keypad.open(path=args.device) as pad:
        pad.set_auto_sleep(args.seconds)
        _emit({"ok": True, "auto_sleep_time": args.seconds}, args.json, "Applied.")
    return 0


def cmd_factory_reset(args) -> int:
    if not args.yes:
        print(
            "This erases the keymap, macros and per-key colours on the device.\n"
            "Re-run with --yes if that is what you want.",
            file=sys.stderr,
        )
        return 1
    with Keypad.open(path=args.device) as pad:
        pad.restore_factory_settings(confirm=True)
        _emit({"ok": True}, args.json, "Factory settings restored.")
    return 0


def _is_nixos() -> bool:
    try:
        return "ID=nixos" in Path("/etc/os-release").read_text()
    except OSError:
        return False


def _declarative_help() -> str:
    """Guidance for distributions where /etc is generated, not edited."""
    if _is_nixos():
        return (
            "/etc/udev/rules.d is read-only on NixOS — it is a symlink into the\n"
            "Nix store, and a file written there would be discarded on the next\n"
            "rebuild. Declare the rule instead. Either use this project's flake:\n"
            "\n"
            "    # flake.nix\n"
            "    inputs.sdcx-keypad.url = \"github:parsaj-dev/sdcx-keypad\";\n"
            "    # then, in your host configuration:\n"
            "    imports = [ inputs.sdcx-keypad.nixosModules.default ];\n"
            "    programs.sdcx-keypad.enable = true;\n"
            "\n"
            "or, without adding an input, add this to configuration.nix:\n"
            "\n"
            "    services.udev.extraRules = ''\n"
            "      KERNEL==\"hidraw*\", SUBSYSTEM==\"hidraw\", "
            "ATTRS{idVendor}==\"0816\", TAG+=\"uaccess\"\n"
            "    '';\n"
            "\n"
            "Then `sudo nixos-rebuild switch` and replug the keypad.\n"
            "Run `sdcx install-udev-rule --print` for the exhaustive rule covering\n"
            "every supported USB ID."
        )
    return (
        f"{UDEV_RULE_PATH} is on a read-only filesystem.\n"
        "Your distribution most likely generates /etc declaratively, so the rule\n"
        "belongs in its configuration rather than being written directly.\n"
        "Run `sdcx install-udev-rule --print` to get the rule to add."
    )


def cmd_install_udev_rule(args) -> int:
    rule = _udev_rule()
    if args.print:
        sys.stdout.write(rule)
        return 0
    try:
        with open(UDEV_RULE_PATH, "w") as handle:
            handle.write(rule)
    except PermissionError:
        print(
            f"Need root to write {UDEV_RULE_PATH}.\n"
            f"Run: sudo sdcx install-udev-rule\n"
            f"Or inspect it first with: sdcx install-udev-rule --print",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        # A read-only /etc means a declarative distribution owns it. Writing the
        # file is not merely blocked there, it is the wrong approach: the next
        # rebuild would discard it. Point at the declarative equivalent instead
        # of suggesting the user fight their package manager.
        if exc.errno != errno.EROFS:
            raise
        print(_declarative_help(), file=sys.stderr)
        return 1
    print(f"Wrote {UDEV_RULE_PATH}")
    print("Reload with: sudo udevadm control --reload-rules && sudo udevadm trigger")
    print("Then replug the keypad.")
    return 0


def cmd_effect(args) -> int:
    from .effects import run_effect, EFFECTS

    if args.name == "list":
        from .effects import effects_manifest

        # The manifest carries each effect's long-form help and its parameter
        # schema, which is what lets a GUI build controls and hover-help without
        # knowing anything about individual effects.
        payload = {"ok": True, "effects": effects_manifest()}
        if args.json:
            _emit(payload, True)
        else:
            for n, e in EFFECTS.items():
                print(f"{n:<12} {e.description}")
        return 0
    return run_effect(args)


# -- parser ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdcx",
        description="Control SDCX / SDINNOVATION programmable keypads (HCY-K006 and family).",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    parser.add_argument("--device", metavar="PATH", help="hidraw node to use (default: first found)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list connected keypads")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("info", help="show firmware, serial, profile")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("modes", help="list the lighting modes this device supports")
    p.set_defaults(func=cmd_modes)

    p = sub.add_parser("keys", help="list addressable keys")
    p.add_argument("--colors", action="store_true", help="also read each key's current colour")
    p.set_defaults(func=cmd_keys)

    light = sub.add_parser("light", help="global lighting").add_subparsers(
        dest="light_command", required=True
    )

    p = light.add_parser("get", help="read the current lighting state")
    p.set_defaults(func=cmd_light_get)

    p = light.add_parser("off", help="turn the RGB off (persists in the keypad)")
    p.set_defaults(func=cmd_light_off)

    p = light.add_parser("mode", help="switch effect, adopting firmware defaults")
    p.add_argument("mode", help="mode name or number, e.g. breath or 2")
    p.set_defaults(func=cmd_light_mode)

    p = light.add_parser("set", help="change individual lighting fields")
    p.add_argument("--mode")
    p.add_argument("--brightness", type=int, choices=range(0, MAX_BRIGHTNESS + 1))
    p.add_argument("--speed", type=int, choices=range(0, MAX_SPEED + 1))
    p.add_argument("--direction", type=int, choices=(0, 1))
    p.add_argument("--color", metavar="#RRGGBB", help="single colour")
    p.add_argument("--palette", action="store_true", help="use the rainbow palette instead")
    p.set_defaults(func=cmd_light_set)

    key = sub.add_parser("key", help="per-key colour").add_subparsers(
        dest="key_command", required=True
    )
    p = key.add_parser("color", help="set one key's colour, or all of them")
    p.add_argument("index", help="key index, or 'all'")
    p.add_argument("color", metavar="#RRGGBB")
    p.set_defaults(func=cmd_key_color)

    p = sub.add_parser("keycodes", help="list the keycode names 'keymap set' accepts")
    p.add_argument("--category", help="one of: " + ", ".join(CATEGORIES))
    p.add_argument("--search", metavar="TEXT", help="substring match on name or code")
    p.set_defaults(func=cmd_keycodes)

    keymap = sub.add_parser("keymap", help="what each key does").add_subparsers(
        dest="keymap_command", required=True
    )

    p = keymap.add_parser("get", help="show each key's current binding")
    p.add_argument("--layer", type=int, default=0)
    p.set_defaults(func=cmd_keymap_get)

    p = keymap.add_parser("set", help="rebind one key, e.g. sdcx keymap set 0 ctrl+c")
    p.add_argument("index", type=int, help="key index; see sdcx keys")
    p.add_argument("keycode", help="keycode name, ctrl+c style combination, or macro:N")
    p.add_argument("--layer", type=int, default=0)
    p.set_defaults(func=cmd_keymap_set)

    p = keymap.add_parser("reset", help="restore the firmware's own key table")
    p.add_argument("--layer", type=int, default=0)
    p.set_defaults(func=cmd_keymap_reset)

    macro = sub.add_parser("macro", help="macro slots").add_subparsers(
        dest="macro_command", required=True
    )

    p = macro.add_parser("get", help="show the stored macros")
    p.add_argument("--all", action="store_true", help="include empty slots")
    p.add_argument("--raw", action="store_true", help="dump the 4096-byte area instead")
    p.set_defaults(func=cmd_macro_get)

    p = macro.add_parser("set", help="record a macro, e.g. sdcx macro set 0 'ctrl+c, a'")
    p.add_argument("slot", type=int, choices=range(MACRO_SLOTS), metavar=f"SLOT(0-{MACRO_SLOTS - 1})")
    p.add_argument("sequence", help="comma-separated keystrokes, each pressed and released")
    p.add_argument("--delay", type=int, default=10, help="milliseconds between events")
    p.set_defaults(func=cmd_macro_set)

    p = macro.add_parser("reset", help="clear every macro slot")
    p.set_defaults(func=cmd_macro_reset)

    p = sub.add_parser("effect", help="host-driven live effects")
    p.add_argument("name", help="effect name, or 'list'")
    p.add_argument("--fps", type=float, default=20.0)
    p.add_argument("--duration", type=float, default=0.0, help="seconds; 0 = until interrupted")
    p.add_argument("--color", metavar="#RRGGBB", default="#7c4dff")
    p.add_argument("--restore", action="store_true", help="restore previous mode on exit")
    try:
        # Parameterised effects register their own flags. Older installs of the
        # package do not have this, and the rest of the CLI must still work.
        from .effects import register_effect_arguments

        register_effect_arguments(p)
    except ImportError:
        pass
    p.set_defaults(func=cmd_effect)

    p = sub.add_parser("profile", help="select a configuration scheme")
    p.add_argument("index", type=int)
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("sleep", help="set auto-sleep time in seconds")
    p.add_argument("seconds", type=int)
    p.set_defaults(func=cmd_sleep)

    p = sub.add_parser("factory-reset", help="erase keymap, macros and colours")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_factory_reset)

    p = sub.add_parser("install-udev-rule", help="grant non-root access permanently")
    p.add_argument("--print", action="store_true", help="print the rule instead of writing it")
    p.set_defaults(func=cmd_install_udev_rule)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (SdcxError, DeviceNotFound, PermissionDenied) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc), "kind": type(exc).__name__}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
