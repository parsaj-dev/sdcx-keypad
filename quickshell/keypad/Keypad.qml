import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.ii.overlay

/**
 * Control panel for an SDCX/SDINNOVATION programmable keypad (HCY-K006 and family).
 *
 * Backed by KeypadService, which shells out to the `sdcx` CLI. The device is
 * hot-pluggable and its config node is root-owned until a udev rule is installed,
 * so the unavailable states are first-class here rather than an afterthought.
 */
StyledOverlayWidget {
    id: root
    minimumWidth: 380
    minimumHeight: 440

    contentItem: OverlayBackground {
        radius: root.contentRadius
        property real padding: Appearance.spacing.snug

        ColumnLayout {
            anchors {
                fill: parent
                margins: parent.padding
            }
            spacing: Appearance.spacing.snug

            SecondaryTabBar {
                id: tabBar
                Layout.fillWidth: true

                currentIndex: Persistent.states.overlay.keypad.tabIndex
                onCurrentIndexChanged: {
                    Persistent.states.overlay.keypad.tabIndex = tabBar.currentIndex;
                }

                SecondaryTabButton {
                    buttonIcon: "lightbulb"
                    buttonText: Translation.tr("Light")
                }
                SecondaryTabButton {
                    buttonIcon: "keyboard"
                    buttonText: Translation.tr("Keys")
                }
                SecondaryTabButton {
                    buttonIcon: "graphic_eq"
                    buttonText: Translation.tr("Live")
                }
                SecondaryTabButton {
                    buttonIcon: "info"
                    buttonText: Translation.tr("Device")
                }
            }

            KeypadContent {
                Layout.fillWidth: true
                Layout.fillHeight: true
                tabIndex: tabBar.currentIndex
            }
        }
    }
}
