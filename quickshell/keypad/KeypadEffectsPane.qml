pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets

/**
 * Host-rendered effects: this machine computes each frame and streams it to the
 * pad as per-key colours. That is what lets an effect show CPU load or battery,
 * which the firmware could never know about, and equally why they stop when
 * this process does.
 *
 * The list and every effect's controls are built from `sdcx effect list --json`,
 * so adding an effect to the driver makes it appear here with no QML change.
 */
ColumnLayout {
    id: root
    spacing: Appearance.spacing.snug

    property var expanded: null

    KeypadNote {
        text: Translation.tr("Rendered by this computer and streamed to the pad. They stop when the widget or session closes; the keypad's own effect returns.")
        icon: "cast"
    }

    StyledListView {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: Appearance.spacing.tight
        clip: true
        model: KeypadService.effects

        delegate: Rectangle {
            id: card
            required property var modelData

            width: ListView.view.width
            implicitHeight: cardColumn.implicitHeight + Appearance.spacing.snug * 2
            radius: Appearance.rounding.small

            readonly property bool running: KeypadService.effectRunning
                && KeypadService.effectName === card.modelData.name
            readonly property bool isExpanded: root.expanded === card.modelData.name
            readonly property var params: card.modelData.params ?? []

            color: card.running
                ? Appearance.colors.colPrimaryContainer
                : Appearance.colors.colLayer1

            Behavior on color {
                animation: Appearance.animation.elementMoveFast.colorAnimation.createObject(this)
            }

            readonly property color foreground: card.running
                ? Appearance.colors.colOnPrimaryContainer
                : Appearance.colors.colOnLayer1

            ColumnLayout {
                id: cardColumn
                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                    margins: Appearance.spacing.snug
                }
                spacing: Appearance.spacing.snug

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Appearance.spacing.snug

                    RippleButton {
                        implicitWidth: Appearance.spacing.controlHeight
                        implicitHeight: Appearance.spacing.controlHeight
                        buttonRadius: Appearance.rounding.full
                        onClicked: KeypadService.toggleEffect(card.modelData.name, KeypadService.hex)
                        contentItem: MaterialSymbol {
                            anchors.centerIn: parent
                            text: card.running ? "stop" : "play_arrow"
                            iconSize: Appearance.font.pixelSize.larger
                            color: card.foreground
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        StyledText {
                            text: card.modelData.name
                            color: card.foreground
                        }

                        StyledText {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            text: card.modelData.description ?? ""
                            font.pixelSize: Appearance.font.pixelSize.smallest
                            color: card.running
                                ? Appearance.colors.colOnPrimaryContainer
                                : Appearance.colors.colSubtext
                        }
                    }

                    // Long-form help lives behind an info affordance rather than
                    // in the list, which would otherwise be a wall of prose.
                    MaterialSymbol {
                        id: infoIcon
                        visible: (card.modelData.help ?? "").length > 0
                        text: "info"
                        iconSize: Appearance.font.pixelSize.large
                        color: Appearance.colors.colSubtext

                        MouseArea {
                            id: infoMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            StyledToolTip {
                                extraVisibleCondition: infoMouse.containsMouse
                                text: card.modelData.help ?? ""
                            }
                        }
                    }

                    RippleButton {
                        visible: card.params.length > 0
                        implicitWidth: Appearance.spacing.controlHeight
                        implicitHeight: Appearance.spacing.controlHeight
                        buttonRadius: Appearance.rounding.full
                        onClicked: root.expanded = card.isExpanded ? null : card.modelData.name
                        contentItem: MaterialSymbol {
                            anchors.centerIn: parent
                            text: card.isExpanded ? "expand_less" : "tune"
                            iconSize: Appearance.font.pixelSize.large
                            color: card.foreground
                        }
                        StyledToolTip { text: Translation.tr("Options") }
                    }
                }

                // Parameter controls, generated from the driver's manifest.
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.bottomMargin: card.isExpanded ? Appearance.spacing.tight : 0
                    visible: card.isExpanded
                    spacing: Appearance.spacing.tight

                    Repeater {
                        model: card.params
                        delegate: EffectParam {
                            required property var modelData
                            Layout.fillWidth: true
                            spec: modelData
                            effectName: card.modelData.name
                            foreground: card.foreground
                        }
                    }
                }
            }
        }
    }

    /**
     * One control for one declared effect parameter. The driver describes each
     * as {name, kind, default, min, max, choices, description}; this maps a kind
     * onto a widget so new parameters need no QML.
     */
    component EffectParam: RowLayout {
        id: param
        required property var spec
        required property string effectName
        property color foreground: Appearance.colors.colOnLayer1

        spacing: Appearance.spacing.snug

        StyledText {
            Layout.preferredWidth: 82
            text: param.spec.name
            font.pixelSize: Appearance.font.pixelSize.smallie
            color: param.foreground

            MouseArea {
                id: labelMouse
                anchors.fill: parent
                hoverEnabled: true
                StyledToolTip {
                    extraVisibleCondition: labelMouse.containsMouse
                        && (param.spec.description ?? "").length > 0
                    text: param.spec.description ?? ""
                }
            }
        }

        Loader {
            Layout.fillWidth: true
            sourceComponent: {
                switch (param.spec.kind) {
                case "bool": return boolControl;
                case "choice": return choiceControl;
                case "color": return colorControl;
                default: return numberControl;
                }
            }
        }

        Component {
            id: numberControl
            StyledSlider {
                configuration: StyledSlider.Configuration.XS
                from: param.spec.min ?? 0
                to: param.spec.max ?? 1
                stepSize: param.spec.kind === "int" ? 1 : 0
                value: KeypadService.effectParam(param.effectName, param.spec.name, param.spec.default)
                usePercentTooltip: false
                tooltipContent: String(Math.round(value * 100) / 100)
                onPressedChanged: {
                    if (!pressed)
                        KeypadService.setEffectParam(param.effectName, param.spec.name, value);
                }
            }
        }

        Component {
            id: boolControl
            StyledSwitch {
                checked: KeypadService.effectParam(param.effectName, param.spec.name, param.spec.default) === true
                onToggled: KeypadService.setEffectParam(param.effectName, param.spec.name, checked)
            }
        }

        Component {
            id: choiceControl
            StyledComboBox {
                model: param.spec.choices ?? []
                currentIndex: Math.max(0, (param.spec.choices ?? []).indexOf(
                    KeypadService.effectParam(param.effectName, param.spec.name, param.spec.default)))
                onActivated: index => KeypadService.setEffectParam(
                    param.effectName, param.spec.name, (param.spec.choices ?? [])[index])
            }
        }

        Component {
            id: colorControl
            RowLayout {
                spacing: Appearance.spacing.tight
                Repeater {
                    model: ["#ff0000", "#ff9500", "#ffee00", "#00ff3c", "#00e5ff", "#0066ff", "#b400ff", "#ffffff"]
                    delegate: Rectangle {
                        id: dot
                        required property string modelData
                        implicitWidth: 18
                        implicitHeight: 18
                        radius: width / 2
                        color: dot.modelData
                        border.width: Qt.colorEqual(
                            KeypadService.effectParam(param.effectName, param.spec.name, param.spec.default),
                            dot.modelData) ? 2 : 1
                        border.color: Appearance.colors.colOutlineVariant
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: KeypadService.setEffectParam(
                                param.effectName, param.spec.name, dot.modelData)
                        }
                    }
                }
            }
        }
    }
}
