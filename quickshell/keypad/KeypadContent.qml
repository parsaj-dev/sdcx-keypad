pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets

/**
 * Tab shell for the keypad widget, plus the states where there is no keypad to
 * talk to. Each pane lives in its own file, because inline components cannot be
 * forward-referenced from inside a sibling inline component, and this widget hit
 * that limit early.
 */
Item {
    id: root
    required property int tabIndex

    // The pad's state can change without us: it has on-device lighting
    // shortcuts, and it can be unplugged. Re-read whenever a pane is shown.
    onTabIndexChanged: KeypadService.refresh()
    Component.onCompleted: KeypadService.refresh()

    StackLayout {
        anchors.fill: parent
        // Every pane needs a live device, so the unavailable state is gated once
        // here rather than repeated in four places.
        currentIndex: KeypadService.ready ? root.tabIndex + 1 : 0

        UnavailableState {}

        KeypadLightPane {}

        KeypadKeysPane {}

        KeypadEffectsPane {}

        KeypadDevicePane {}
    }

    component UnavailableState: Item {
        ColumnLayout {
            anchors.centerIn: parent
            width: parent.width - Appearance.spacing.wide * 2
            spacing: Appearance.spacing.normal

            MaterialSymbol {
                Layout.alignment: Qt.AlignHCenter
                text: {
                    if (KeypadService.permissionDenied)
                        return "lock";
                    return KeypadService.toolAvailable ? "usb_off" : "extension_off";
                }
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
                    if (KeypadService.toolChecked && !KeypadService.toolAvailable)
                        return Translation.tr("Install it from github.com/parsaj-dev/sdcx-keypad");
                    if (KeypadService.permissionDenied)
                        return Translation.tr("Run `sudo sdcx install-udev-rule`, then replug the keypad.");
                    if (KeypadService.error.length > 0)
                        return KeypadService.error;
                    return "";
                }
            }

            RippleButton {
                Layout.alignment: Qt.AlignHCenter
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
}
