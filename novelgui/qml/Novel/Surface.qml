pragma ComponentBehavior: Bound
import QtQuick

// A lifted surface (style B): lighter fill, baked shadow of a level, 1 px hairline of light on the top edge.
// level 0 = flat (no shadow, no hairline).
Rectangle {
    id: surface

    property int level: 2
    property bool hairline: level > 0

    color: Theme.lift
    radius: Theme.rControl

    Shadow {
        visible: surface.level > 0
        level: "sh" + Math.max(1, surface.level)
    }
    readonly property bool round: surface.width === surface.height && surface.radius * 2 >= surface.width - 0.5
    // a round surface: the light follows the curve (a thin crescent, like an inset 1 px light), not a flat stroke that
    // sticks out of the circle
    Item {
        visible: surface.hairline && surface.round
        width: parent.width
        height: Math.ceil(parent.height / 2)     // the top half only: the shifted fill must not grow the bottom
        z: 2
        clip: true
        Rectangle {
            width: surface.width
            height: surface.height
            radius: surface.radius
            color: Theme.hairline
        }
        Rectangle {
            y: 1
            width: surface.width
            height: surface.height
            radius: surface.radius
            color: surface.color
        }
    }
    Rectangle {
        visible: surface.hairline && !surface.round
        x: surface.radius * 0.7
        y: 0
        z: 2
        width: surface.width - 2 * x
        height: 1
        color: Theme.hairline
    }
}
