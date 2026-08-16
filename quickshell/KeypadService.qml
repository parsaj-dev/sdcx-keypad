pragma Singleton
pragma ComponentBehavior: Bound

/**
 * Backing service for the keypad overlay widget.
 *
 * Wraps the `sdcx` CLI (https://github.com/parsaj-dev/sdcx-keypad), which drives
 * SDCX/SDINNOVATION programmable macropads over their vendor HID interface.
 * Every sdcx subcommand accepts --json and answers with a single object, so this
 * service never parses human prose.
 *
 * The device is a piece of hardware that may be unplugged at any moment and whose
 * config node is root-owned until a udev rule is installed. Both are ordinary
 * states here, not errors to hide: `available` and `permissionDenied` drive the
 * widget's empty states.
 */

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    // `sdcx` is expected on PATH. Overridable for a checkout that is not installed.
    property string binaryPath: "sdcx"

    property bool toolChecked: false
    property bool toolAvailable: false

    property bool loading: false
    property bool available: false
    property bool permissionDenied: false
    property string error: ""

    property var device: null          // { path, usb_id, model, key_count, verified }
    property var light: null           // { mode, brightness, speed, direction, color, h, s, v }
    property string modeName: ""
    property string hex: "#000000"
    property int maxBrightness: 4
    property int maxSpeed: 4

    property var modes: []             // [{ value, name, brightness, speed, color, ... }]
    property var keys: []              // [{ index, label, row, col, kind, color }]
    property var effects: []           // [{ name, description }]

    property bool effectRunning: false
    property string effectName: ""

    readonly property bool ready: available && light !== null

    signal refreshed()

    // -- helpers -----------------------------------------------------------

    function _fail(message) {
        root.error = message;
        root.available = false;
        root.loading = false;
    }

    /**
     * sdcx reports failure as {ok:false, error, kind}. PermissionDenied is the
     * expected first-run state — the config interface is root-only until the udev
     * rule is installed — so it is surfaced separately rather than as an error.
     */
    function _handleFailure(payload) {
        root.permissionDenied = (payload.kind === "PermissionDenied");
        root.available = false;
        root.error = payload.error ?? "unknown error";
    }

    function refresh() {
        if (!root.toolChecked) {
            probeProc.running = true;
            return;
        }
        if (!root.toolAvailable || lightProc.running)
            return;
        root.loading = true;
        root._exitSeen = false;
        lightProc.running = true;
    }

    // -- availability probe -------------------------------------------------

    Process {
        id: probeProc
        command: ["sh", "-c", `command -v ${root.binaryPath}`]
        stdout: StdioCollector {
            id: probeCollector
            onStreamFinished: {
                root.toolChecked = true;
                root.toolAvailable = probeCollector.text.trim().length > 0;
                if (!root.toolAvailable) {
                    root._fail(`\`${root.binaryPath}\` is not on PATH`);
                    return;
                }
                root.refresh();
                modesProc.running = true;
                effectsProc.running = true;
            }
        }
    }

    // -- lighting state -----------------------------------------------------

    // Quickshell 0.3.0 does not emit `exited` when a binary fails to exec, only
    // `runningChanged`. Without this guard a failed launch leaves loading stuck
    // true forever. See docs/13-shell-widgets.md §2.
    property bool _exitSeen: false

    Process {
        id: lightProc
        command: [root.binaryPath, "--json", "light", "get"]
        stdout: StdioCollector {
            id: lightCollector
            onStreamFinished: {
                const text = lightCollector.text.trim();
                if (text.length === 0)
                    return;
                try {
                    const parsed = JSON.parse(text);
                    if (!parsed.ok) {
                        root._handleFailure(parsed);
                        return;
                    }
                    root.light = parsed.light;
                    root.modeName = parsed.mode_name ?? "";
                    root.hex = parsed.hex ?? "#000000";
                    root.maxBrightness = parsed.max_brightness ?? 4;
                    root.maxSpeed = parsed.max_speed ?? 4;
                    root.available = true;
                    root.permissionDenied = false;
                    root.error = "";
                    keysProc.running = true;
                    root.refreshed();
                } catch (e) {
                    root._fail("could not parse `sdcx light get --json`");
                }
            }
        }
        onExited: {
            root._exitSeen = true;
            root.loading = false;
        }
        onRunningChanged: {
            if (lightProc.running || root._exitSeen)
                return;
            root._fail(`could not execute ${root.binaryPath}`);
        }
    }

    Process {
        id: deviceProc
        command: [root.binaryPath, "--json", "list"]
        stdout: StdioCollector {
            id: deviceCollector
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(deviceCollector.text.trim());
                    root.device = (parsed.devices && parsed.devices.length > 0) ? parsed.devices[0] : null;
                } catch (e) {
                    root.device = null;
                }
            }
        }
    }

    Process {
        id: modesProc
        command: [root.binaryPath, "--json", "modes"]
        stdout: StdioCollector {
            id: modesCollector
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(modesCollector.text.trim());
                    root.modes = parsed.ok ? parsed.modes : [];
                } catch (e) {
                    root.modes = [];
                }
            }
        }
    }

    Process {
        id: keysProc
        command: [root.binaryPath, "--json", "keys", "--colors"]
        stdout: StdioCollector {
            id: keysCollector
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(keysCollector.text.trim());
                    root.keys = parsed.ok ? parsed.keys : [];
                } catch (e) {
                    root.keys = [];
                }
            }
        }
    }

    Process {
        id: effectsProc
        command: [root.binaryPath, "--json", "effect", "list"]
        stdout: StdioCollector {
            id: effectsCollector
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(effectsCollector.text.trim());
                    root.effects = parsed.ok ? parsed.effects : [];
                } catch (e) {
                    root.effects = [];
                }
            }
        }
    }

    // -- writes -------------------------------------------------------------

    // Writes are fire-and-forget followed by a re-read: the firmware adjusts
    // fields we did not send (switching mode adopts its own defaults for speed
    // and direction), so the authoritative state always comes back from the device.
    Process { id: writeProc }

    function _write(argv) {
        if (root.effectRunning)
            root.stopEffect();
        writeProc.command = [root.binaryPath, "--json"].concat(argv);
        writeProc.running = true;
        resyncTimer.restart();
    }

    Timer {
        id: resyncTimer
        interval: 120
        onTriggered: root.refresh()
    }

    function setMode(value) { root._write(["light", "mode", String(value)]); }
    function off() { root._write(["light", "off"]); }
    function setBrightness(value) { root._write(["light", "set", "--brightness", String(Math.round(value))]); }
    function setSpeed(value) { root._write(["light", "set", "--speed", String(Math.round(value))]); }
    function setDirection(value) { root._write(["light", "set", "--direction", String(value)]); }
    function setColor(hex) { root._write(["light", "set", "--color", hex]); }
    function usePalette() { root._write(["light", "set", "--palette"]); }
    function setKeyColor(index, hex) { root._write(["key", "color", String(index), hex]); }
    function setAllKeyColors(hex) { root._write(["key", "color", "all", hex]); }

    // -- effects ------------------------------------------------------------

    // An effect is a long-running host-side render loop, not a device setting:
    // it holds the process open and streams per-key colours. Only one at a time.
    Process {
        id: effectProc
        onRunningChanged: {
            if (!effectProc.running) {
                root.effectRunning = false;
                root.effectName = "";
                root.refresh();
            }
        }
    }

    function startEffect(name, hex) {
        if (root.effectRunning)
            root.stopEffect();
        effectProc.command = [root.binaryPath, "effect", name, "--color", hex ?? root.hex];
        effectProc.running = true;
        root.effectRunning = true;
        root.effectName = name;
    }

    function stopEffect() {
        if (!effectProc.running)
            return;
        effectProc.signal(15); // SIGTERM; the effect restores state in its finally block
        root.effectRunning = false;
        root.effectName = "";
    }

    function toggleEffect(name, hex) {
        if (root.effectRunning && root.effectName === name)
            root.stopEffect();
        else
            root.startEffect(name, hex);
    }

    // -- lifecycle ----------------------------------------------------------

    Component.onCompleted: {
        probeProc.running = true;
        deviceProc.running = true;
    }
}
