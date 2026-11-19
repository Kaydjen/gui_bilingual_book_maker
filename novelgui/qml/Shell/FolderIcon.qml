pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A small folder drawn from two rectangles (no image, no icon font).
Item {
    id: icon

    property color color: Theme.dim

    implicitWidth: 16
    implicitHeight: 13

    Rectangle {
        x: 0
        y: 0
        width: 7
        height: 4
        radius: 1.5
        border.width: 1.2
        border.color: icon.color
        color: "transparent"
    }
    Rectangle {
        x: 0
        y: 2
        width: icon.width
        height: icon.height - 2
        radius: 2
        border.width: 1.2
        border.color: icon.color
        color: Theme.field
    }
}
