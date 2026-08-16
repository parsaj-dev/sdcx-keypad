pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets

/**
 * The keypad's own lighting: effects that run on its firmware and are stored in
 * its flash. These keep working with the machine off, which is the whole reason
 * they are a separate pane from the host-rendered effects.
 */
StyledFlickable {
    id: root
    contentHeight: column.implicitHeight
    clip: true

    /** Whether the currently selected firmware mode honours a given field. */
    function modeSupports(field: string): bool {
        const mode = KeypadService.modes.find(m => m.value === KeypadService.light?.mode);
        return mode ? mode[field] === true : false;
    }

    ColumnLayout {
        id: column
        width: root.width
        spacing: Appearance.spacing.normal

        KeypadNote {
            text: Translation.tr("Runs on the keypad itself and is saved to it, so these keep working when this computer is off.")
            icon: "memory"
        }

        ContentSubsectionLabel {
            text: Translation.tr("Effect")
        }

        FlowButtonGroup {
            Layout.fillWidth: true

            Repeater {
                model: KeypadService.modes
                delegate: GroupButton {
                    id: modeButton
                    required property var modelData

                    baseWidth: implicitContentWidth + Appearance.spacing.loose
                    toggled: KeypadService.light?.mode === modeButton.modelData.value
                    onClicked: KeypadService.setMode(modeButton.modelData.value)

                    contentItem: StyledText {
                        horizontalAlignment: Text.AlignHCenter
                        text: modeButton.modelData.name
                        color: modeButton.toggled
                            ? Appearance.colors.colOnPrimary
                            : Appearance.colors.colOnLayer1
                    }
                }
            }
        }

        // Brightness and speed are 0-4 integer steps in the firmware, not
        // continuous ranges, and each mode honours only some of them. The
        // capability flags come from the device's own descriptor.
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

        // Palette mode is the firmware cycling hues on its own, which is a
        // different thing from any one colour, so it is a toggle above the
        // picker rather than another swatch inside it.
        ConfigSwitch {
            Layout.fillWidth: true
            visible: root.modeSupports("color")
            text: Translation.tr("Cycle all colours")
            buttonIcon: "gradient"
            checked: KeypadService.light?.color === 0
            onCheckedChanged: {
                if (checked && KeypadService.light?.color !== 0)
                    KeypadService.usePalette();
            }
        }

        KeypadColorPicker {
            Layout.fillWidth: true
            visible: root.modeSupports("color") && KeypadService.light?.color === 1
            selected: KeypadService.hex
            onPicked: chosen => KeypadService.setColor(chosen.toString().substring(0, 7))
        }

        RippleButton {
            Layout.fillWidth: true
            implicitHeight: Appearance.spacing.controlHeight
            buttonRadius: Appearance.rounding.small
            colBackground: Appearance.colors.colLayer1
            colBackgroundHover: Appearance.colors.colLayer1Hover
            onClicked: KeypadService.off()

            contentItem: RowLayout {
                spacing: Appearance.spacing.tight
                Item { Layout.fillWidth: true }
                MaterialSymbol {
                    text: "light_off"
                    iconSize: Appearance.font.pixelSize.large
                    color: Appearance.colors.colOnLayer1
                }
                StyledText {
                    text: Translation.tr("Turn lights off")
                    color: Appearance.colors.colOnLayer1
                }
                Item { Layout.fillWidth: true }
            }
        }

        Item { Layout.fillHeight: true }
    }

    /**
     * A 0-N stepped slider. ConfigSlider exposes neither `stepSize` nor
     * `pressed`, and the write has to be deferred to release because each one is
     * a USB round-trip.
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
}
