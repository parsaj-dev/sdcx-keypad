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
| `keypad/Keypad.qml` | The overlay widget shell — title bar, tabs. |
| `keypad/KeypadContent.qml` | The three panes: lighting, per-key colour, effects. |

## Installing into an `ii`-style shell

1. Copy `KeypadService.qml` into `services/` and `keypad/` into `modules/ii/overlay/`.
2. Register the widget in the three places `StyledOverlayWidget` documents:
   - `modules/ii/overlay/OverlayContext.qml` — add
     `{ identifier: "keypad", materialSymbol: "keyboard" }` to `availableWidgets`.
   - `modules/ii/overlay/OverlayWidgetDelegateChooser.qml` — add
     `import qs.modules.ii.overlay.keypad` and
     `DelegateChoice { roleValue: "keypad"; Keypad {} }`.
   - `modules/common/Persistent.qml` — add a `keypad` `JsonObject` under `overlay` with
     `pinned`, `clickthrough`, `x`, `y`, `width`, `height` and `tabIndex`.
3. Make sure `sdcx` is on `PATH`. If it is not, set `KeypadService.binaryPath` to its
   absolute path.

## How the service talks to the device

Every `sdcx` subcommand accepts `--json` and answers with a single object carrying an `ok`
field, so the service never parses human prose. Two consequences worth knowing if you adapt it:

- **Writes are followed by a re-read.** The firmware adjusts fields you did not send — switching
  effect adopts its own defaults for speed and direction — so the device, not the UI, is
  authoritative about what the current state is.
- **`PermissionDenied` is a state, not an error.** The config interface is root-owned until the
  udev rule is installed, which is the expected condition on first run. The widget shows an
  actionable empty state for it instead of a failure.

Effects are a long-running host-side render loop rather than a device setting, so the service
holds that process open and stops it with `SIGTERM`; `sdcx` catches that and restores the
previous lighting on the way out.
