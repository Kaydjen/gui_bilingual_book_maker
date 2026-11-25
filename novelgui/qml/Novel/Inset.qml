pragma ComponentBehavior: Bound
import QtQuick

// A slightly inset (darker) well: fill, the 1 px edge and a soft shade along the top edge.
Rectangle {
    id: inset

    property color edge: Theme.fieldLine
    property bool shade: true

    color: Theme.field
    radius: Theme.rField
    border.width: 1
    border.color: edge

    Rectangle {
        visible: inset.shade
        x: 1
        y: 1
        width: parent.width - 2
        height: 3
        radius: inset.radius
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.8) }
            GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0) }
        }
    }
}
