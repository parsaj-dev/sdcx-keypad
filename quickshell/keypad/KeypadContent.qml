pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.modules.common
import qs.modules.common.functions
import qs.modules.common.widgets

/**
 * The three panes of the keypad widget. Split out of Keypad.qml so the wrapper
 * stays a thin declaration of chrome, matching the Resources/VolumeMixer shape.
 */
Item {
    id: root
    required property int tabIndex

    // A small fixed palette for one-tap colour changes. Drawn from the theme so
    // it tracks the wallpaper rather than introducing colours of its own; the
    // last entry is a neutral white for when the pad should just be legible.
    readonly property list<string> swatches: [
        Appearance.m3colors.m3primary,
        Appearance.m3colors.m3secondary,
        Appearance.m3colors.m3tertiary,
        Appearance.m3colors.m3error,
        "#ffffff",
    ]

    // The pad's own state is authoritative and can change from the device itself
    // (it has on-key lighting shortcuts), so re-read whenever the pane is shown.
    onTabIndexChanged: KeypadService.refresh()
    Component.onCompleted: KeypadService.refresh()

    StackLayout {
        anchors.fill: parent
        // Every pane collapses to the same unavailable state, so gate once here.
        currentIndex: KeypadService.ready ? root.tabIndex + 1 : 0

        UnavailableState {}

        LightPane {}

        KeysPane {}

        EffectsPane {}
    }

    // -- unavailable -------------------------------------------------------

    component UnavailableState: Item {
        ColumnLayout {
            anchors.centerIn: parent
            width: parent.width - Appearance.spacing.wide * 2
            spacing: Appearance.spacing.normal

            MaterialSymbol {
                Layout.alignment: Qt.AlignHCenter
                text: KeypadService.permissionDenied ? "lock" : (KeypadService.toolAvailable ? "usb_off" : "extension_off")
                iconSize: 48
                color: Appearance.colors.colSubtext
            }

            StyledText {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: Appearance.font.pixelSize.normal
                color: Appearance.colors.colOnSurface
                text: {
                    if (!KeypadService.toolChecked)
                        return Translation.tr("Looking for the keypad…");
                    if (!KeypadService.toolAvailable)
                        return Translation.tr("`sdcx` is not installed");
                    if (KeypadService.permissionDenied)
                        return Translation.tr("No permission to reach the keypad");
                    return Translation.tr("No keypad connected");
                }
            }

            StyledText {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: Appearance.font.pixelSize.smallie
                color: Appearance.colors.colSubtext
                visible: text.length > 0
                text: {
                    if (!KeypadService.toolAvailable && KeypadService.toolChecked)
                        return Translation.tr("Install it from github.com/parsaj-dev/sdcx-keypad");
                    if (KeypadService.permissionDenied)
                        return Translation.tr("Run `sudo sdcx install-udev-rule`, then replug the keypad.");
                    return "";
                }
            }

            RippleButton {
                Layout.alignment: Qt.AlignHCenter
                visible: KeypadService.toolAvailable
                implicitHeight: Appearance.spacing.controlHeight
                buttonRadius: Appearance.rounding.full
                colBackground: Appearance.colors.colSecondaryContainer
                colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                onClicked: {
                    KeypadService.toolChecked = false;
                    KeypadService.refresh();
                }
                contentItem: RowLayout {
                    spacing: Appearance.spacing.tight
                    MaterialSymbol {
                        text: "refresh"
                        iconSize: Appearance.font.pixelSize.large
                        color: Appearance.colors.colOnSecondaryContainer
                    }
                    StyledText {
                        text: Translation.tr("Retry")
                        color: Appearance.colors.colOnSecondaryContainer
                    }
                }
            }
        }
    }

    // -- lighting ----------------------------------------------------------

    /**
     * Brightness and speed are 0-N integer steps in the firmware, not continuous
     * ranges, so this snaps and shows a divider per step rather than a percentage.
     * The write is deferred to release: dragging would otherwise fire one USB
     * round-trip per pixel.
     */
    component SteppedSlider: RowLayout {
        id: stepped
        property string label: ""
        property string icon: ""
        property int steps: 4
        property real value: 0
        signal committed(int level)

        spacing: Appearance.spacing.normal

        MaterialSymbol {
            text: stepped.icon
            iconSize: Appearance.font.pixelSize.larger
            color: Appearance.colors.colOnSurfaceVariant
        }

        StyledText {
            Layout.preferredWidth: 76
            text: stepped.label
            color: Appearance.colors.colOnSurfaceVariant
        }

        StyledSlider {
            id: slider
            Layout.fillWidth: true
            configuration: StyledSlider.Configuration.XS
            from: 0
            to: stepped.steps
            stepSize: 1
            snapMode: Slider.SnapAlways
            usePercentTooltip: false
            tooltipContent: `${Math.round(slider.value)} / ${stepped.steps}`
            value: stepped.value
            onPressedChanged: {
                if (!slider.pressed)
                    stepped.committed(Math.round(slider.value));
            }
        }
    }

    component Swatch: Rectangle {
        id: swatch
        required property color swatchColor
        property bool selected: false
        signal picked()

        implicitWidth: Appearance.spacing.controlHeight
        implicitHeight: Appearance.spacing.controlHeight
        radius: Appearance.rounding.full
        color: swatch.swatchColor
        border.width: swatch.selected ? 2 : 1
        border.color: swatch.selected ? Appearance.colors.colOnSurface : Appearance.colors.colOutlineVariant

        Behavior on border.width {
            animation: Appearance.animation.elementMoveFast.numberAnimation.createObject(this)
        }

        MaterialSymbol {
            anchors.centerIn: parent
            visible: swatch.selected
            text: "check"
            iconSize: Appearance.font.pixelSize.normal
            // Pick the tick colour off the swatch's own luminance so it stays
            // readable on both a near-black and a near-white sample.
            color: (0.299 * swatch.swatchColor.r + 0.587 * swatch.swatchColor.g
                + 0.114 * swatch.swatchColor.b) > 0.55 ? "#000000" : "#ffffff"
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: swatch.picked()
        }
    }

    component LightPane: StyledFlickable {
        contentHeight: lightColumn.implicitHeight
        clip: true

        ColumnLayout {
            id: lightColumn
            width: parent.width
            spacing: Appearance.spacing.normal

            ContentSubsectionLabel {
                text: Translation.tr("Effect")
            }

            FlowButtonGroup {
                Layout.fillWidth: true
                Repeater {
                    model: KeypadService.modes
                    delegate: GroupButton {
                        required property var modelData
                        baseWidth: implicitContentWidth + Appearance.spacing.loose
                        toggled: KeypadService.light?.mode === modelData.value
                        onClicked: KeypadService.setMode(modelData.value)
                        contentItem: StyledText {
                            horizontalAlignment: Text.AlignHCenter
                            text: modelData.name
                            color: parent.toggled ? Appearance.colors.colOnPrimary : Appearance.colors.colOnLayer1
                        }
                    }
                }
            }

            SteppedSlider {
                Layout.fillWidth: true
                visible: root.modeSupports("brightness")
                label: Translation.tr("Brightness")
                icon: "brightness_medium"
                steps: KeypadService.maxBrightness
                value: KeypadService.light?.brightness ?? 0
                onCommitted: level => KeypadService.setBrightness(level)
            }

            SteppedSlider {
                Layout.fillWidth: true
                visible: root.modeSupports("speed")
                label: Translation.tr("Speed")
                icon: "speed"
                steps: KeypadService.maxSpeed
                value: KeypadService.light?.speed ?? 0
                onCommitted: level => KeypadService.setSpeed(level)
            }

            ContentSubsectionLabel {
                visible: root.modeSupports("color")
                text: Translation.tr("Colour")
            }

            RowLayout {
                Layout.fillWidth: true
                visible: root.modeSupports("color")
                spacing: Appearance.spacing.snug

                Repeater {
                    model: root.swatches
                    delegate: Swatch {
                        required property string modelData
                        swatchColor: modelData
                        selected: KeypadService.light?.color === 1
                            && Qt.colorEqual(KeypadService.hex, modelData)
                        onPicked: KeypadService.setColor(modelData)
                    }
                }

                Item { Layout.fillWidth: true }

                // Palette mode is the firmware cycling hues itself, which is a
                // different thing from any single colour — hence its own control.
                RippleButton {
                    implicitWidth: Appearance.spacing.controlHeight
                    implicitHeight: Appearance.spacing.controlHeight
                    buttonRadius: Appearance.rounding.full
                    toggled: KeypadService.light?.color === 0
                    onClicked: KeypadService.usePalette()
                    contentItem: MaterialSymbol {
                        anchors.centerIn: parent
                        text: "gradient"
                        iconSize: Appearance.font.pixelSize.larger
                        color: parent.toggled ? Appearance.colors.colOnPrimary : Appearance.colors.colOnLayer1
                    }
                    StyledToolTip { text: Translation.tr("Cycle the full palette") }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }


    function modeSupports(field: string): bool {
        const mode = KeypadService.modes.find(m => m.value === KeypadService.light?.mode);
        return mode ? mode[field] === true : false;
    }


    // -- keys --------------------------------------------------------------

    component KeysPane: ColumnLayout {
        spacing: Appearance.spacing.snug

        StyledText {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            visible: KeypadService.light?.mode !== 5
            font.pixelSize: Appearance.font.pixelSize.smallie
            color: Appearance.colors.colSubtext
            text: Translation.tr("Per-key colours only show in Custom mode.")
        }

        RippleButton {
            Layout.fillWidth: true
            visible: KeypadService.light?.mode !== 5
            implicitHeight: Appearance.spacing.controlHeight
            buttonRadius: Appearance.rounding.small
            colBackground: Appearance.colors.colPrimaryContainer
            colBackgroundHover: Appearance.colors.colPrimaryContainerHover
            onClicked: KeypadService.setMode(5)
            contentItem: StyledText {
                horizontalAlignment: Text.AlignHCenter
                text: Translation.tr("Switch to Custom")
                color: Appearance.colors.colOnPrimaryContainer
            }
        }

        // The pad drawn as it physically sits: two rows of three, knob on the right.
        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: 4
            rowSpacing: Appearance.spacing.snug
            columnSpacing: Appearance.spacing.snug

            Repeater {
                model: KeypadService.keys.filter(k => k.kind === "key")
                delegate: KeyCap {
                    required property var modelData
                    keyData: modelData
                    Layout.row: modelData.row
                    Layout.column: modelData.col
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
            }

            // The three knob actions share one encoder, so they are drawn as a
            // single control spanning both rows rather than as three keys.
            KnobControl {
                Layout.row: 0
                Layout.column: 3
                Layout.rowSpan: 2
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Appearance.spacing.snug

            StyledText {
                text: Translation.tr("All keys")
                font.pixelSize: Appearance.font.pixelSize.smallie
                color: Appearance.colors.colSubtext
            }
            Item { Layout.fillWidth: true }
            Repeater {
                model: root.swatches
                delegate: Swatch {
                    required property string modelData
                    swatchColor: modelData
                    implicitWidth: Appearance.spacing.snug * 3
                    implicitHeight: Appearance.spacing.snug * 3
                    onPicked: KeypadService.setAllKeyColors(modelData)
                }
            }
        }
    }

    component KeyCap: Rectangle {
        id: cap
        required property var keyData
        property color capColor: cap.keyData.color ?? "#000000"

        implicitWidth: 56
        implicitHeight: 44
        radius: Appearance.rounding.small
        color: Appearance.colors.colLayer1
        border.width: 1
        border.color: Appearance.colors.colOutlineVariant

        // The key's assigned colour as a filled bar rather than the whole cap:
        // an unlit key would otherwise be indistinguishable from the surface.
        Rectangle {
            anchors {
                left: parent.left
                right: parent.right
                bottom: parent.bottom
                margins: Appearance.spacing.tight
            }
            height: Appearance.spacing.snug
            radius: Appearance.rounding.unsharpen
            color: cap.capColor
            border.width: 1
            border.color: Appearance.colors.colOutlineVariant

            Behavior on color {
                animation: Appearance.animation.elementMoveFast.colorAnimation.createObject(this)
            }
        }

        StyledText {
            anchors {
                top: parent.top
                horizontalCenter: parent.horizontalCenter
                topMargin: Appearance.spacing.tight
            }
            text: cap.keyData.index
            font.family: Appearance.font.family.numbers
            font.pixelSize: Appearance.font.pixelSize.smaller
            color: Appearance.colors.colSubtext
        }

        StyledToolTip {
            text: `${cap.keyData.label} — ${cap.capColor}`
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            // Cycle the swatch palette on click: a full colour picker per key is
            // more chrome than a six-key pad warrants.
            onClicked: {
                const next = root.swatches[(cap.keyData.index + 1) % root.swatches.length];
                KeypadService.setKeyColor(cap.keyData.index, next);
            }
        }
    }

    component KnobControl: Rectangle {
        radius: Appearance.rounding.full
        color: Appearance.colors.colLayer1
        border.width: 1
        border.color: Appearance.colors.colOutlineVariant
        implicitWidth: 56

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 0
            MaterialSymbol {
                Layout.alignment: Qt.AlignHCenter
                text: "rotate_right"
                iconSize: Appearance.font.pixelSize.huge
                color: Appearance.colors.colOnSurfaceVariant
            }
            StyledText {
                Layout.alignment: Qt.AlignHCenter
                text: Translation.tr("Knob")
                font.pixelSize: Appearance.font.pixelSize.smallest
                color: Appearance.colors.colSubtext
            }
        }

        StyledToolTip {
            text: Translation.tr("Rotate for volume, press to mute")
        }
    }

    // -- effects -----------------------------------------------------------

    component EffectsPane: ColumnLayout {
        spacing: Appearance.spacing.snug

        StyledText {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.pixelSize: Appearance.font.pixelSize.smallie
            color: Appearance.colors.colSubtext
            text: Translation.tr("Live effects rendered on this machine and streamed to the pad. They stop when you close the widget's effect or change a light setting.")
        }

        StyledListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Appearance.spacing.tight
            clip: true
            model: KeypadService.effects

            delegate: RippleButton {
                required property var modelData
                width: ListView.view.width
                implicitHeight: Appearance.spacing.controlHeightLarge + Appearance.spacing.snug
                buttonRadius: Appearance.rounding.small
                toggled: KeypadService.effectRunning && KeypadService.effectName === modelData.name
                onClicked: KeypadService.toggleEffect(modelData.name, KeypadService.hex)

                contentItem: RowLayout {
                    anchors.margins: Appearance.spacing.snug
                    spacing: Appearance.spacing.snug

                    MaterialSymbol {
                        text: parent.parent.toggled ? "stop_circle" : "play_circle"
                        iconSize: Appearance.font.pixelSize.huge
                        color: parent.parent.toggled ? Appearance.colors.colOnPrimary : Appearance.colors.colOnLayer1
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        StyledText {
                            text: modelData.name
                            color: parent.parent.parent.toggled ? Appearance.colors.colOnPrimary : Appearance.colors.colOnLayer1
                        }
                        StyledText {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            text: modelData.description
                            font.pixelSize: Appearance.font.pixelSize.smallest
                            color: parent.parent.parent.toggled ? Appearance.colors.colOnPrimary : Appearance.colors.colSubtext
                        }
                    }
                }
            }
        }
    }
}
