pragma Singleton
pragma ComponentBehavior: Bound

/**
 * Backing service for the keypad overlay widget.
 *
 * Wraps the `sdcx` CLI (https://github.com/parsaj-dev/sdcx-keypad), which drives
 * SDCX/SDINNOVATION programmable macropads over their vendor HID interface.
 * Every sdcx subcommand accepts --json and answers with a single object carrying
 * an `ok` field, so this service never parses human prose.
 *
 * Two things it models deliberately:
 *
 * - The device is hot-pluggable and its config node is root-owned until a udev
 *   rule is installed. Both are ordinary states, not errors, and drive the
 *   widget's empty states rather than being hidden.
 * - Feature detection is by probing the CLI, not by assuming a version. An older
 *   sdcx without `keymap` still gets a fully working lighting UI.
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
    property bool keymapSupported: false

    property bool loading: false
    property bool available: false
    property bool permissionDenied: false
    property string error: ""

    property var device: null          // { path, usb_id, model, key_count, verified }
    property var info: null            // { firmware, serial, profile, profile_count, ... }
    property var light: null           // { mode, brightness, speed, direction, color, h, s, v }
    property string modeName: ""
    property string hex: "#000000"
    property int maxBrightness: 4
    property int maxSpeed: 4

    property var modes: []             // [{ value, name, brightness, speed, color, ... }]
    property var keys: []              // [{ index, label, row, col, kind, color, binding }]
    property var effects: []           // [{ name, description, help, params: [...] }]

    property bool effectRunning: false
    property string effectName: ""

    /**
     * Chosen effect parameters, keyed "<effect>.<param>". Held here rather than
     * in the widget so a running effect's settings survive the overlay closing.
     */
    property var effectParams: ({})

    readonly property bool ready: available && light !== null

    signal refreshed()

    // -- helpers -----------------------------------------------------------

    function _fail(message) {
        root.error = message;
        root.available = false;
        root.loading = false;
    }

    function _handleFailure(payload) {
        root.permissionDenied = (payload.kind === "PermissionDenied");
        root.available = false;
        root.error = payload.error ?? "unknown error";
    }

    function _parse(text, onOk) {
        const trimmed = (text ?? "").trim();
        if (trimmed.length === 0)
            return;
        try {
            const parsed = JSON.parse(trimmed);
            if (parsed.ok === false) {
                root._handleFailure(parsed);
                return;
            }
            onOk(parsed);
        } catch (e) {
            root._fail("could not parse sdcx JSON output");
        }
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
        infoProc.running = true;
    }

    function effectParam(effect, name, fallback) {
        const value = root.effectParams[`${effect}.${name}`];
        return value === undefined ? fallback : value;
    }

    function setEffectParam(effect, name, value) {
        // Reassigning the whole object rather than mutating: QML only notifies
        // on assignment, so a mutated var property would not update bindings.
        const next = Object.assign({}, root.effectParams);
        next[`${effect}.${name}`] = value;
        root.effectParams = next;
        if (root.effectRunning && root.effectName === effect)
            root.startEffect(effect); // restart so the new value takes effect
    }

    // -- availability probes -------------------------------------------------

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
                keymapProbeProc.running = true;
            }
        }
    }

    // Key remapping arrived after the first release, so its presence is probed
    // rather than assumed; the UI degrades to colour-only without it.
    Process {
        id: keymapProbeProc
        command: ["sh", "-c", `${root.binaryPath} keymap --help >/dev/null 2>&1 && echo yes`]
        stdout: StdioCollector {
            id: keymapProbeCollector
            onStreamFinished: {
                root.keymapSupported = keymapProbeCollector.text.trim() === "yes";
                if (root.keymapSupported)
                    keymapProc.running = true;
            }
        }
    }

    // -- reads ---------------------------------------------------------------

    // Quickshell 0.3.0 does not emit `exited` when a binary fails to exec, only
    // `runningChanged`. Without this guard a failed launch leaves loading stuck
    // true forever. See docs/13-shell-widgets.md §2.
    property bool _exitSeen: false

    Process {
        id: lightProc
        command: [root.binaryPath, "--json", "light", "get"]
        stdout: StdioCollector {
            id: lightCollector
            onStreamFinished: root._parse(lightCollector.text, parsed => {
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
            })
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
        id: infoProc
        command: [root.binaryPath, "--json", "info"]
        stdout: StdioCollector {
            id: infoCollector
            onStreamFinished: root._parse(infoCollector.text, parsed => {
                root.info = parsed.config ?? null;
                if (parsed.device)
                    root.device = parsed.device;
            })
        }
    }

    Process {
        id: deviceProc
        command: [root.binaryPath, "--json", "list"]
        stdout: StdioCollector {
            id: deviceCollector
            onStreamFinished: root._parse(deviceCollector.text, parsed => {
                root.device = (parsed.devices && parsed.devices.length > 0) ? parsed.devices[0] : null;
            })
        }
    }

    Process {
        id: modesProc
        command: [root.binaryPath, "--json", "modes"]
        stdout: StdioCollector {
            id: modesCollector
            onStreamFinished: root._parse(modesCollector.text, parsed => {
                root.modes = parsed.modes ?? [];
            })
        }
    }

    Process {
        id: keysProc
        command: [root.binaryPath, "--json", "keys", "--colors"]
        stdout: StdioCollector {
            id: keysCollector
            onStreamFinished: root._parse(keysCollector.text, parsed => {
                root.keys = root._mergeBindings(parsed.keys ?? [], root._bindings);
            })
        }
    }

    /** index -> binding name, from the last successful `keymap get`. */
    property var _bindings: ({})

    function _mergeBindings(keys, bindings) {
        return keys.map(k => Object.assign({}, k, { binding: bindings[k.index] ?? "" }));
    }

    Process {
        id: keymapProc
        command: [root.binaryPath, "--json", "keymap", "get"]
        stdout: StdioCollector {
            id: keymapCollector
            onStreamFinished: root._parse(keymapCollector.text, parsed => {
                const map = {};
                (parsed.keys ?? []).forEach(k => {
                    map[k.index] = k.binding ?? k.name ?? "";
                });
                root._bindings = map;
                root.keys = root._mergeBindings(root.keys, map);
            })
        }
    }

    Process {
        id: effectsProc
        command: [root.binaryPath, "--json", "effect", "list"]
        stdout: StdioCollector {
            id: effectsCollector
            onStreamFinished: root._parse(effectsCollector.text, parsed => {
                root.effects = parsed.effects ?? [];
            })
        }
    }

    // -- writes --------------------------------------------------------------

    // Writes are fire-and-forget followed by a re-read: the firmware adjusts
    // fields we did not send (switching mode adopts its own defaults for speed
    // and direction), so the device stays authoritative about its own state.
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
        interval: 140
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
    function setProfile(index) { root._write(["profile", String(index)]); }

    function setKeyBinding(index, keycode) {
        if (!root.keymapSupported || keycode.length === 0)
            return;
        writeProc.command = [root.binaryPath, "--json", "keymap", "set", String(index), keycode];
        writeProc.running = true;
        keymapResync.restart();
    }

    Timer {
        id: keymapResync
        interval: 160
        onTriggered: keymapProc.running = true
    }

    // -- effects -------------------------------------------------------------

    // An effect is a long-running host-side render loop, not a device setting:
    // the process stays open streaming per-key colours. Only one at a time.
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

    /** Build the CLI flags for an effect from its manifest and current settings. */
    function _effectArgs(name) {
        const spec = root.effects.find(e => e.name === name);
        const argv = [root.binaryPath, "effect", name];
        if (!spec)
            return argv;
        (spec.params ?? []).forEach(param => {
            const value = root.effectParam(name, param.name, param.default);
            if (value === undefined || value === null)
                return;
            // The manifest carries the exact flag string; deriving it here would
            // be a second place to keep in sync with the driver.
            const flag = param.flag ?? ("--" + String(param.name).replace(/_/g, "-"));
            if (param.kind === "bool") {
                if (value === true)
                    argv.push(flag);   // store_true flags take no value
            } else {
                argv.push(flag, String(value));
            }
        });
        return argv;
    }

    function startEffect(name) {
        if (effectProc.running)
            root.stopEffect();
        effectProc.command = root._effectArgs(name);
        effectProc.running = true;
        root.effectRunning = true;
        root.effectName = name;
    }

    function stopEffect() {
        if (!effectProc.running)
            return;
        effectProc.signal(15); // SIGTERM; the effect restores lighting on the way out
        root.effectRunning = false;
        root.effectName = "";
    }

    function toggleEffect(name) {
        if (root.effectRunning && root.effectName === name)
            root.stopEffect();
        else
            root.startEffect(name);
    }

    // -- lifecycle -----------------------------------------------------------

    Component.onCompleted: {
        probeProc.running = true;
        deviceProc.running = true;
    }
}
