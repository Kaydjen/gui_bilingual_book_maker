pragma ComponentBehavior: Bound
import QtQuick

// The content root of a window: keyboard focus mode tracking, the content area and the one tooltip layer on top.
Item {
    id: root

    default property alias content: area.data

    focus: true
    Keys.onPressed: event => {
        Focus.byKey = true
        Tips.dismiss()
        event.accepted = false
    }

    Item {
        id: area
        anchors.fill: parent
    }
    TipLayer {}
}
