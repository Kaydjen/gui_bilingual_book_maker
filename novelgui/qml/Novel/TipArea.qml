pragma ComponentBehavior: Bound
import QtQuick

// Gives its parent a tooltip. `tip`: string | {text, facts} | [text, facts]. Fill the element to explain.
Item {
    id: area

    property var tip: ""

    anchors.fill: parent

    HoverHandler {
        id: hover
        onHoveredChanged: {
            if (hovered)
                Tips.arm(area, area.tip, point.scenePosition)
            else
                Tips.leave(area)
        }
    }
}
