pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets

/**
 * Colour picker for the keypad's LEDs.
 *
 * Deliberately does NOT use the Material You palette for its swatches. Those are
 * surface colours chosen to sit behind text, and in a dark theme primary,
 * secondary and tertiary are all pale near-greys — on an RGB LED they are
 * indistinguishable from white. A swatch here has to be the literal colour the
 * LED will emit, so the presets are fixed, saturated hues.
 *
 * The chrome around them still comes from the theme; only the colour samples
 * themselves are fixed.
 */
Item {
    id: root

    property color selected: "#ff0000"
    /** Emitted only on release/commit, never mid-drag — each change is a USB write. */
    signal picked(color chosen)

    implicitHeight: layout.implicitHeight

    // Twelve saturated hues plus white. Full value and saturation because the
    // brightness of the LED is controlled separately; a dimmed swatch here would
    // just be a lie about what the key will look like.
    readonly property list<string> presets: [
        "#ff0000", "#ff6a00", "#ffb300", "#ffee00",
        "#7dff00", "#00ff3c", "#00ffb3", "#00e5ff",
        "#0066ff", "#7b3cff", "#ff00d4", "#ff0066",
        "#ffffff",
    ]

    function _hueOf(c: color): real { return c.hsvHue < 0 ? 0 : c.hsvHue; }

    ColumnLayout {
        id: layout
        width: parent.width
        spacing: Appearance.spacing.snug

        GridLayout {
            Layout.fillWidth: true
            columns: 7
            rowSpacing: Appearance.spacing.tight
            columnSpacing: Appearance.spacing.tight

            Repeater {
                model: root.presets
                delegate: Rectangle {
                    id: swatch
                    required property string modelData

                    Layout.fillWidth: true
                    implicitHeight: 24
                    radius: Appearance.rounding.verysmall
                    color: swatch.modelData

                    readonly property bool isSelected: Qt.colorEqual(root.selected, swatch.modelData)
                    border.width: swatch.isSelected ? 2 : 1
                    border.color: swatch.isSelected
                        ? Appearance.colors.colOnSurface
                        : Appearance.colors.colOutlineVariant

                    Behavior on border.width {
                        animation: Appearance.animation.elementMoveFast.numberAnimation.createObject(this)
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.selected = swatch.modelData;
                            root.picked(swatch.modelData);
                        }
                        StyledToolTip {
                            extraVisibleCondition: parent.containsMouse
                            text: swatch.modelData
                        }
                    }
                }
            }
        }

        // Free choice beyond the presets. Hue and saturation only: value is what
        // the pad's own brightness control already does, and exposing both would
        // give two controls that fight over the same visible result.
        ChannelSlider {
            id: hueSlider
            label: Translation.tr("Hue")
            from: 0
            to: 359
            value: root._hueOf(root.selected) * 360
            onCommitted: level => root._commitHsv(level, satSlider.value)
            gradientStops: [
                "#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ff0000"
            ]
        }

        ChannelSlider {
            id: satSlider
            label: Translation.tr("Saturation")
            from: 0
            to: 100
            value: root.selected.hsvSaturation * 100
            onCommitted: level => root._commitHsv(hueSlider.value, level)
            gradientStops: [
                Qt.hsva(root._hueOf(root.selected), 0, 1, 1),
                Qt.hsva(root._hueOf(root.selected), 1, 1, 1)
            ]
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Appearance.spacing.snug

            StyledText {
                text: Translation.tr("Hex")
                font.pixelSize: Appearance.font.pixelSize.smallie
                color: Appearance.colors.colSubtext
            }

            MaterialTextField {
                id: hexField
                Layout.fillWidth: true
                text: root.selected.toString().substring(0, 7)
                onAccepted: {
                    const value = hexField.text.trim();
                    if (/^#?[0-9a-fA-F]{6}$/.test(value)) {
                        const normalised = value.startsWith("#") ? value : "#" + value;
                        root.selected = normalised;
                        root.picked(normalised);
                    } else {
                        hexField.text = root.selected.toString().substring(0, 7);
                    }
                }
            }
        }
    }

    function _commitHsv(hue: real, saturation: real): void {
        const chosen = Qt.hsva(hue / 360, saturation / 100, 1, 1);
        root.selected = chosen;
        root.picked(chosen);
    }

    /**
     * A slider whose track shows the value being chosen. Built on a plain Slider
     * rather than StyledSlider because the point is the gradient behind the
     * handle, which StyledSlider's track does not expose.
     */
    component ChannelSlider: RowLayout {
        id: channel
        property string label: ""
        property real from: 0
        property real to: 100
        property alias value: slider.value
        property list<string> gradientStops: []
        signal committed(real level)

        spacing: Appearance.spacing.snug

        StyledText {
            Layout.preferredWidth: 68
            text: channel.label
            font.pixelSize: Appearance.font.pixelSize.smallie
            color: Appearance.colors.colOnSurfaceVariant
        }

        Item {
            Layout.fillWidth: true
            implicitHeight: 22

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 8
                radius: height / 2
                border.width: 1
                border.color: Appearance.colors.colOutlineVariant
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    // Stops are positioned evenly; a Repeater cannot build a
                    // Gradient's stop list, so this maps the strings by index.
                    GradientStop { position: 0.0;  color: channel.gradientStops[0] ?? "transparent" }
                    GradientStop { position: 0.17; color: channel.gradientStops[1] ?? channel.gradientStops[channel.gradientStops.length - 1] ?? "transparent" }
                    GradientStop { position: 0.33; color: channel.gradientStops[2] ?? channel.gradientStops[channel.gradientStops.length - 1] ?? "transparent" }
                    GradientStop { position: 0.5;  color: channel.gradientStops[3] ?? channel.gradientStops[channel.gradientStops.length - 1] ?? "transparent" }
                    GradientStop { position: 0.67; color: channel.gradientStops[4] ?? channel.gradientStops[channel.gradientStops.length - 1] ?? "transparent" }
                    GradientStop { position: 0.83; color: channel.gradientStops[5] ?? channel.gradientStops[channel.gradientStops.length - 1] ?? "transparent" }
                    GradientStop { position: 1.0;  color: channel.gradientStops[6] ?? channel.gradientStops[channel.gradientStops.length - 1] ?? "transparent" }
                }
            }

            Slider {
                id: slider
                anchors.fill: parent
                from: channel.from
                to: channel.to
                stepSize: 1

                background: null
                handle: Rectangle {
                    x: slider.visualPosition * (slider.availableWidth - width)
                    y: (slider.height - height) / 2
                    implicitWidth: 14
                    implicitHeight: 20
                    radius: Appearance.rounding.unsharpenmore
                    color: Appearance.colors.colOnSurface
                    border.width: 2
                    border.color: Appearance.m3colors.m3surface
                }

                // Committing on release rather than on every pixel: each change
                // is a USB round-trip to the keypad.
                onPressedChanged: {
                    if (!slider.pressed)
                        channel.committed(slider.value);
                }
            }
        }
    }
}
