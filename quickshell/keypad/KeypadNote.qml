pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.modules.common
import qs.modules.common.widgets

/**
 * A one-line explainer at the top of a pane.
 *
 * The Light and Effects panes both change the colour of the same LEDs by
 * completely different mechanisms — one runs on the keypad's own firmware and
 * persists, the other is rendered by this machine and stops when it does. That
 * distinction is invisible from the controls alone, so each pane states it.
 */
Rectangle {
    id: root
    required property string text
    property string icon: "info"

    Layout.fillWidth: true
    implicitHeight: row.implicitHeight + Appearance.spacing.snug * 2
    radius: Appearance.rounding.small
    color: Appearance.colors.colLayer1

    RowLayout {
        id: row
        anchors {
            fill: parent
            margins: Appearance.spacing.snug
        }
        spacing: Appearance.spacing.snug

        MaterialSymbol {
            Layout.alignment: Qt.AlignTop
            text: root.icon
            iconSize: Appearance.font.pixelSize.large
            color: Appearance.colors.colSubtext
        }

        StyledText {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: root.text
            font.pixelSize: Appearance.font.pixelSize.smallie
            color: Appearance.colors.colSubtext
        }
    }
}
