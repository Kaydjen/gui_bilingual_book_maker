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
    Rectangle {
        visible: surface.hairline
        x: surface.radius * 0.7
        y: 0
        z: 2
        width: surface.width - 2 * x
        height: 1
        color: Theme.hairline
    }
}
