import QtQuick
import Novel

// A flat button on a hovered list row (queue rows: Stop, Don't resume), off any panel.
AppRoot {
    Rectangle {
        anchors.fill: parent
        color: Theme.pane
    }
    Rectangle {
        x: 20
        y: 20
        width: 400
        height: 40
        color: Theme.rowHover
        Pill {
            objectName: "rowFlat"
            kind: "flat"
            text: "Stop"
            anchors.verticalCenter: parent.verticalCenter
            x: 12
        }
    }
}
