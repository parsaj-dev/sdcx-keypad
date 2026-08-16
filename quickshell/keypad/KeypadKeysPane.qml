pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets

/**
 * The pad drawn as it physically sits, with per-key colour and key bindings.
 *
 * Selecting a key rather than cycling its colour on click: a key has two
 * independent properties here (what it sends, what colour it is) and a click
 * that silently changed one of them would make the other unreachable.
 */
ColumnLayout {
    id: root
    spacing: Appearance.spacing.snug

    property int selectedIndex: -1

    readonly property var selectedKey: KeypadService.keys.find(k => k.index === root.selectedIndex) ?? null
    readonly property var mainKeys: KeypadService.keys.filter(k => k.kind === "key")
    readonly property var knobKeys: KeypadService.keys.filter(k => k.kind === "knob")

    KeypadNote {
        visible: KeypadService.light?.mode !== 5
        text: Translation.tr("Per-key colours only appear in the Custom effect — in any other mode the keypad repaints them itself.")
        icon: "palette"
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

    // The pad: two rows of three switches, the encoder to their right.
    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 108
        spacing: Appearance.spacing.snug

        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: 3
            rowSpacing: Appearance.spacing.tight
            columnSpacing: Appearance.spacing.tight

            Repeater {
                model: root.mainKeys
                delegate: KeyCap {
                    required property var modelData
                    keyData: modelData
                    Layout.row: modelData.row
                    Layout.column: modelData.col
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
            }
        }

        // One physical encoder with three actions, so it is drawn as one control
        // and its three bindings are listed beneath rather than as three keys.
        Rectangle {
            Layout.preferredWidth: 64
            Layout.fillHeight: true
            radius: Appearance.rounding.full
            color: Appearance.colors.colLayer1
            border.width: 1
            border.color: Appearance.colors.colOutlineVariant

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

            HoverHandler { id: knobHover }
            StyledToolTip {
                extraVisibleCondition: knobHover.hovered
                text: Translation.tr("Rotate for volume, press to mute")
            }
        }
    }

    // Knob actions are addressable keys too, just not ones you can click on the
    // drawing, so they get their own selectable row.
    RowLayout {
        Layout.fillWidth: true
        spacing: Appearance.spacing.tight

        Repeater {
            model: root.knobKeys
            delegate: RippleButton {
                id: knobButton
                required property var modelData

                Layout.fillWidth: true
                implicitHeight: 26
                buttonRadius: Appearance.rounding.verysmall
                toggled: root.selectedIndex === knobButton.modelData.index
                onClicked: root.selectedIndex = knobButton.modelData.index

                contentItem: StyledText {
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: knobButton.modelData.label.replace("Knob ", "")
                    font.pixelSize: Appearance.font.pixelSize.smallest
                    color: knobButton.toggled
                        ? Appearance.colors.colOnPrimary
                        : Appearance.colors.colOnLayer1
                }
            }
        }
    }

    // Editor for whichever key is selected.
    StyledFlickable {
        Layout.fillWidth: true
        Layout.fillHeight: true
        contentHeight: editor.implicitHeight
        clip: true

        ColumnLayout {
            id: editor
            width: parent.width
            spacing: Appearance.spacing.snug

            StyledText {
                Layout.fillWidth: true
                visible: root.selectedKey === null
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: Translation.tr("Pick a key to change what it sends and how it lights up.")
                font.pixelSize: Appearance.font.pixelSize.smallie
                color: Appearance.colors.colSubtext
            }

            ContentSubsectionLabel {
                visible: root.selectedKey !== null
                text: root.selectedKey ? root.selectedKey.label : ""
            }

            RowLayout {
                Layout.fillWidth: true
                visible: root.selectedKey !== null
                spacing: Appearance.spacing.snug

                StyledText {
                    text: Translation.tr("Sends")
                    Layout.preferredWidth: 60
                    font.pixelSize: Appearance.font.pixelSize.smallie
                    color: Appearance.colors.colOnSurfaceVariant
                }

                MaterialTextField {
                    id: bindingField
                    Layout.fillWidth: true
                    enabled: KeypadService.keymapSupported
                    placeholderText: Translation.tr("e.g. ctrl+c, F5, volume_up")
                    text: root.selectedKey?.binding ?? ""
                    onAccepted: {
                        if (root.selectedIndex >= 0)
                            KeypadService.setKeyBinding(root.selectedIndex, bindingField.text.trim());
                    }
                }
            }

            StyledText {
                Layout.fillWidth: true
                visible: root.selectedKey !== null && !KeypadService.keymapSupported
                wrapMode: Text.WordWrap
                text: Translation.tr("Key binding needs a newer sdcx (`sdcx keymap`).")
                font.pixelSize: Appearance.font.pixelSize.smallest
                color: Appearance.colors.colSubtext
            }

            ContentSubsectionLabel {
                visible: root.selectedKey !== null
                text: Translation.tr("Key colour")
            }

            KeypadColorPicker {
                Layout.fillWidth: true
                visible: root.selectedKey !== null
                selected: root.selectedKey?.color ?? "#000000"
                onPicked: chosen => {
                    if (root.selectedIndex >= 0)
                        KeypadService.setKeyColor(root.selectedIndex, chosen.toString().substring(0, 7));
                }
            }

            RippleButton {
                Layout.fillWidth: true
                implicitHeight: Appearance.spacing.controlHeight
                buttonRadius: Appearance.rounding.small
                colBackground: Appearance.colors.colLayer1
                colBackgroundHover: Appearance.colors.colLayer1Hover
                onClicked: allColorPicker.visible = !allColorPicker.visible
                contentItem: StyledText {
                    horizontalAlignment: Text.AlignHCenter
                    text: Translation.tr("Set every key at once")
                    color: Appearance.colors.colOnLayer1
                }
            }

            KeypadColorPicker {
                id: allColorPicker
                Layout.fillWidth: true
                visible: false
                selected: "#ffffff"
                onPicked: chosen => KeypadService.setAllKeyColors(chosen.toString().substring(0, 7))
            }
        }
    }

    component KeyCap: Rectangle {
        id: cap
        required property var keyData
        readonly property color capColor: cap.keyData.color ?? "#000000"
        readonly property bool isSelected: root.selectedIndex === cap.keyData.index

        implicitWidth: 56
        implicitHeight: 44
        radius: Appearance.rounding.small
        color: cap.isSelected ? Appearance.colors.colPrimaryContainer : Appearance.colors.colLayer1
        border.width: cap.isSelected ? 2 : 1
        border.color: cap.isSelected
            ? Appearance.colors.colPrimary
            : Appearance.colors.colOutlineVariant

        Behavior on color {
            animation: Appearance.animation.elementMoveFast.colorAnimation.createObject(this)
        }

        StyledText {
            anchors {
                top: parent.top
                horizontalCenter: parent.horizontalCenter
                topMargin: Appearance.spacing.tight
            }
            width: parent.width - Appearance.spacing.snug
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: cap.keyData.binding && cap.keyData.binding.length > 0
                ? cap.keyData.binding
                : String(cap.keyData.index)
            font.pixelSize: Appearance.font.pixelSize.smallest
            color: cap.isSelected
                ? Appearance.colors.colOnPrimaryContainer
                : Appearance.colors.colSubtext
        }

        // The assigned colour as a bar rather than the whole cap: an unlit key
        // would otherwise be indistinguishable from the surface behind it.
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

        MouseArea {
            id: capMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.selectedIndex = cap.keyData.index

            // StyledToolTip defaults to always-visible when its parent has no
            // `hovered` property, which a bare Rectangle does not.
            StyledToolTip {
                extraVisibleCondition: capMouse.containsMouse
                text: `${cap.keyData.label} — ${cap.capColor}`
            }
        }
    }
}
