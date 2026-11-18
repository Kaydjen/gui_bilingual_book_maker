pragma ComponentBehavior: Bound
import QtQuick

// The keyboard focus ring (9.12): 1 px light ring 2 px outside the control, only after a key, never after a click.
Rectangle {
    id: ring

    property Item target: parent
    property real inner: 6

    visible: target && target.activeFocus && Focus.byKey
    x: -3
    y: -3
    width: target ? target.width + 6 : 0
    height: target ? target.height + 6 : 0
    radius: inner + 2
    color: "transparent"
    border.width: 1
    border.color: Theme.ring
    enabled: false
}
