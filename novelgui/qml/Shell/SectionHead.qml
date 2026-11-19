pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A small-caps section heading of Settings with an optional `+` at its right end.
Item {
    id: head

    property string text: ""
    property bool plus: false
    property var tip: ""
    property var plusTip: ""
    signal plusClicked()

    height: 22

    AppText {
        id: label
        height: parent.height
        text: head.text
        color: Theme.dim
        font.pixelSize: 12
        font.letterSpacing: 0.4
        TipArea { tip: head.tip }
    }
    Item {
        visible: head.plus
        objectName: head.objectName + "Plus"
        anchors.right: parent.right
        width: 24
        height: parent.height
        Rectangle {
            anchors.fill: parent
            radius: Theme.rRow
            color: Theme.lift2
            visible: plusHover.hovered
        }
        AppText {
            anchors.centerIn: parent
            text: "+"
            font.pixelSize: 16
            color: plusHover.hovered ? Theme.bright : Theme.dim
        }
        HoverHandler { id: plusHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: head.plusClicked() }
        TipArea { tip: head.plusTip }
    }
}
