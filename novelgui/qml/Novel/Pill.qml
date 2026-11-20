pragma ComponentBehavior: Bound
import QtQuick

// A pill button (mock .pill). kind: "" normal | "main" bright bold | "flat" no fill | "off" disabled | "accent" red text.
Item {
    id: pill

    property string text: ""
    property string kind: ""
    property var tip: ""
    readonly property bool off: kind === "off"
    readonly property bool hovered: hover.hovered
    readonly property bool onCard: Theme.onPanel(pill)
    property bool onLift: false             // on the lifted message card (#262626): one more step
    readonly property color textColor: {
        if (kind === "off")
            return Theme.faint
        if (kind === "accent")
            return Theme.accent
        if (kind === "flat")
            return hovered ? Theme.bright : Theme.dim
        return kind === "main" || hovered ? Theme.bright : Theme.text
    }
    signal clicked()

    implicitWidth: label.implicitWidth + 28
    implicitHeight: Theme.pillHeight
    activeFocusOnTab: !off

    Surface {
        objectName: pill.objectName !== "" ? pill.objectName + "Fill" : ""
        anchors.fill: parent
        level: pill.kind === "flat" || pill.off ? 0 : 1
        radius: Theme.rControl
        color: {
            if (pill.off)
                return Theme.pillOff
            if (pill.kind === "flat")
                return pill.hovered ? (pill.onCard ? Theme.pillOnPanel : Theme.menu) : "transparent"
            if (pill.onLift)
                return pill.hovered ? Theme.pillOnLiftHover : Theme.pillOnLift
            return Theme.pillFill(pill.onCard, pill.hovered)
        }
    }
    AppText {
        id: label
        anchors.centerIn: parent
        text: pill.text
        color: pill.textColor
        font.weight: pill.kind === "main" ? Font.DemiBold : Font.Normal
    }
    HoverHandler {
        id: hover
        cursorShape: pill.off ? Qt.ArrowCursor : Qt.PointingHandCursor
    }
    TapHandler {
        enabled: !pill.off
        onTapped: pill.clicked()
    }
    TipArea { tip: pill.tip }
    FocusRing { target: pill; inner: Theme.rControl }
    Keys.onReturnPressed: if (!off) clicked()
    Keys.onSpacePressed: if (!off) clicked()
}
