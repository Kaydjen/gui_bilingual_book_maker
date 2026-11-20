pragma ComponentBehavior: Bound
import QtQuick

// Base of a list row delegate. Shows the roles `selected` (soft background) and `current` (lifted: lighter surface, shadow,
// one pixel up) and passes the pointer to the DataList that owns the list. Children go into the cell row.
Item {
    id: base

    property int rowIndex: -1
    property bool selected: false
    property bool current: false
    property bool dimmed: false
    readonly property bool hovered: hover.hovered
    property real leftPad: 8
    default property alias cells: cellRow.data
    property var owner: lookup()
    function lookup() {
        var v = ListView.view ? Object(ListView.view) : null     // the DataList puts `owner` on its list
        return v ? v.owner : null
    }

    // what a press on the row does (cells that take their own clicks call it to behave as the rest of the row)
    function pressRow(button, modifiers) {
        if (owner)
            owner.pressedAt(rowIndex, button, (modifiers & Qt.ControlModifier) !== 0, (modifiers & Qt.ShiftModifier) !== 0)
    }
    function dragRow(item, x, y) {
        if (owner)
            owner.draggedTo(item.mapToItem(owner.contentItem, x, y))
    }

    width: ListView.view ? ListView.view.width : 200
    height: Theme.rowHeight

    Item {
        id: face
        x: 6
        width: parent.width - 12
        height: parent.height
        y: base.current ? -1 : 0
        z: base.current ? 1 : 0

        Surface {
            visible: base.current
            anchors.fill: parent
            level: 2
            radius: Theme.rRow
            color: Theme.lift
        }
        Rectangle {
            visible: !base.current && (base.selected || base.hovered)
            anchors.fill: parent
            radius: Theme.rRow
            color: base.selected ? Theme.rowSelected : Theme.rowHover
        }
        Row {
            id: cellRow
            x: base.leftPad
            height: parent.height
            opacity: base.dimmed ? 0.55 : 1
        }
        Rectangle {
            // keyboard cursor: the ring sits inside the cursor row (selection = background, focus = ring)
            visible: base.current && Focus.byKey && !!base.owner && base.owner.activeFocus
            anchors.fill: parent
            radius: Theme.rRow
            color: "transparent"
            border.width: 1
            border.color: Theme.ring
        }
    }
    HoverHandler { id: hover }
    MouseArea {
        id: mouse
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPressed: event => base.pressRow(event.button, event.modifiers)
        onPositionChanged: event => {
            if (pressed)
                base.dragRow(mouse, event.x, event.y)
        }
        onDoubleClicked: if (base.owner) base.owner.rowActivated(base.rowIndex)
    }
}
