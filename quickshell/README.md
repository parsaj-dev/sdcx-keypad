# Quickshell integration

A reference copy of the [Quickshell](https://quickshell.org) overlay widget built on `sdcx`.
These files are taken from a working install on top of
[end-4/dots-hyprland](https://github.com/end-4/dots-hyprland)'s `ii` shell, where the widget
lives in the Super+G overlay alongside the other miniapps.

They are here as a worked example rather than a drop-in package: the widget depends on that
shell's `Appearance`, `Persistent` and `qs.modules.common.widgets` singletons, so it will need
adapting for a different Quickshell config. The service is the reusable part.

## Files

| file | role |
|---|---|
| `KeypadService.qml` | Singleton wrapping the `sdcx` CLI. All device state and every write goes through here. |
| `keypad/Keypad.qml` | The overlay widget shell: title bar and tabs. |
| `keypad/KeypadContent.qml` | Tab switching, plus the states where no keypad is reachable. |
| `keypad/KeypadLightPane.qml` | Firmware lighting: effect, brightness, speed, colour. |
| `keypad/KeypadKeysPane.qml` | The pad drawn to scale, per-key colour and key bindings. |
| `keypad/KeypadEffectsPane.qml` | Host-rendered effects, built from `sdcx effect list --json`. |
| `keypad/KeypadDevicePane.qml` | Firmware version, USB ID, profile switching. |
| `keypad/KeypadColorPicker.qml` | Preset swatches, hue/saturation sliders, hex entry. |
| `keypad/KeypadNote.qml` | The one-line explainer shown at the top of a pane. |

Each pane is a separate file rather than an inline component because a QML inline
component cannot be forward-referenced from inside a sibling inline component.

## Installing into an `ii`-style shell

1. Copy `KeypadService.qml` into `services/` and `keypad/` into `modules/ii/overlay/`.
2. Register the widget in the three places `StyledOverlayWidget` documents:
   - `modules/ii/overlay/OverlayContext.qml`: add
     `{ identifier: "keypad", materialSymbol: "keyboard" }` to `availableWidgets`.
   - `modules/ii/overlay/OverlayWidgetDelegateChooser.qml`: add
     `import qs.modules.ii.overlay.keypad` and
     `DelegateChoice { roleValue: "keypad"; Keypad {} }`.
   - `modules/common/Persistent.qml`: add a `keypad` `JsonObject` under `overlay` with
     `pinned`, `clickthrough`, `x`, `y`, `width`, `height` and `tabIndex`.
3. Make sure `sdcx` is on `PATH`. If it is not, set `KeypadService.binaryPath` to its
   absolute path.

A new QML singleton is not picked up by hot reload. After copying `KeypadService.qml`
in, restart Quickshell or every reference reports `ReferenceError: KeypadService is not
defined` even though the configuration loads cleanly.

## How the service talks to the device

Every `sdcx` subcommand accepts `--json` and answers with a single object carrying an `ok`
field, so the service never parses human prose. Two consequences worth knowing if you adapt it:

- **Writes are followed by a re-read.** The firmware adjusts fields that were not sent:
  switching effect adopts its own defaults for speed and direction. The device, not the
  UI, is authoritative about the current state.
- **Feature detection is by probing, not by version.** `keymap` arrived after the first
  release, so the service runs `sdcx keymap --help` and hides binding controls if it fails.
- **The effect list is data.** Each effect's parameters, ranges and help text come from
  `sdcx effect list --json`, so adding an effect to the driver makes it appear in the UI
  with its own controls and no QML change.
- **`PermissionDenied` is a state, not an error.** The config interface is root-owned until the
  udev rule is installed, which is the expected condition on first run. The widget shows an
  actionable empty state for it instead of a failure.

Effects are a long-running host-side render loop rather than a device setting, so the service
holds that process open and stops it with `SIGTERM`; `sdcx` catches that and restores the
previous lighting on the way out.
