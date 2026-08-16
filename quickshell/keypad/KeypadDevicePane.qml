pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets

/**
 * What the pad reports about itself, plus the settings that are neither lighting
 * nor keys: which stored profile is active, and when it sleeps.
 */
StyledFlickable {
    id: root
    contentHeight: column.implicitHeight
    clip: true

    ColumnLayout {
        id: column
        width: root.width
        spacing: Appearance.spacing.snug

        ContentSubsectionLabel {
            text: Translation.tr("Device")
        }

        InfoRow {
            label: Translation.tr("Model")
            value: KeypadService.device?.model ?? "-"
        }
        InfoRow {
            label: Translation.tr("USB ID")
            value: KeypadService.device?.usb_id ?? "-"
        }
        InfoRow {
            label: Translation.tr("Firmware")
            value: KeypadService.info?.firmware !== undefined ? String(KeypadService.info.firmware) : "-"
        }
        InfoRow {
            label: Translation.tr("Node")
            value: KeypadService.device?.path ?? "-"
        }

        // A layout the driver has not had transcribed still does global lighting
        // correctly, but cannot address individual keys, which is worth saying plainly.
        StyledText {
            Layout.fillWidth: true
            visible: KeypadService.device !== null && KeypadService.device.verified === false
            wrapMode: Text.WordWrap
            text: Translation.tr("This model's key layout is unverified, so per-key colour and bindings are unavailable. Global lighting works.")
            font.pixelSize: Appearance.font.pixelSize.smallest
            color: Appearance.colors.colSubtext
        }

        ContentSubsectionLabel {
            visible: (KeypadService.info?.profile_count ?? 0) > 1
            text: Translation.tr("Profile")
        }

        // The pad stores several complete configurations and switches between
        // them on-device; this just selects which one is live.
        FlowButtonGroup {
            Layout.fillWidth: true
            visible: (KeypadService.info?.profile_count ?? 0) > 1

            Repeater {
                model: KeypadService.info?.profile_count ?? 0
                delegate: GroupButton {
                    id: profileButton
                    required property int index

                    baseWidth: 44
                    toggled: KeypadService.info?.profile === profileButton.index
                    onClicked: KeypadService.setProfile(profileButton.index)
                    contentItem: StyledText {
                        horizontalAlignment: Text.AlignHCenter
                        text: profileButton.index + 1
                        color: profileButton.toggled
                            ? Appearance.colors.colOnPrimary
                            : Appearance.colors.colOnLayer1
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        RippleButton {
            Layout.fillWidth: true
            implicitHeight: Appearance.spacing.controlHeight
            buttonRadius: Appearance.rounding.small
            colBackground: Appearance.colors.colLayer1
            colBackgroundHover: Appearance.colors.colLayer1Hover
            onClicked: KeypadService.refresh()
            contentItem: RowLayout {
                spacing: Appearance.spacing.tight
                Item { Layout.fillWidth: true }
                MaterialSymbol {
                    text: "refresh"
                    iconSize: Appearance.font.pixelSize.large
                    color: Appearance.colors.colOnLayer1
                }
                StyledText {
                    text: Translation.tr("Re-read from device")
                    color: Appearance.colors.colOnLayer1
                }
                Item { Layout.fillWidth: true }
            }
        }
    }

    component InfoRow: RowLayout {
        id: infoRow
        property string label: ""
        property string value: ""

        Layout.fillWidth: true
        spacing: Appearance.spacing.snug

        StyledText {
            text: infoRow.label
            font.pixelSize: Appearance.font.pixelSize.smallie
            color: Appearance.colors.colSubtext
        }
        Item { Layout.fillWidth: true }
        StyledText {
            text: infoRow.value
            font {
                family: Appearance.font.family.numbers
                pixelSize: Appearance.font.pixelSize.smallie
            }
            color: Appearance.colors.colOnSurface
        }
    }
}
