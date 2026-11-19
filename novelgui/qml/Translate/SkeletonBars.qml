pragma ComponentBehavior: Bound
import QtQuick
import Novel

// Two quiet bars where an answer is still to come (the Sample tab): they breathe with the `glint` the owner animates.
Column {
    id: bars

    property real glint: 0

    spacing: 8
    Repeater {
        model: [0.8, 0.45]
        delegate: Rectangle {
            required property real modelData
            width: bars.width * modelData
            height: 9
            radius: 2
            color: Theme.mix(Theme.s2, "#242424", bars.glint)
        }
    }
}
