pragma ComponentBehavior: Bound
import QtQuick

// Draws the one tooltip over everything. Put it last in the window root (it fills the root).
Item {
    id: tipLayer

    anchors.fill: parent
    z: 10000

    function clamp(v, lo, hi) {
        return Math.max(lo, Math.min(v, hi))
    }

    PointHandler {
        acceptedButtons: Qt.AllButtons
        onActiveChanged: {
            Tips.dismiss()
            Focus.byKey = false
        }
    }

    Tip {
        id: bubble
        objectName: "tip"
        visible: Tips.shown
        text: Tips.text
        facts: Tips.facts
        readonly property point from: tipLayer.mapFromItem(null, Tips.at.x, Tips.at.y)
        x: tipLayer.clamp(from.x + 14, 4, tipLayer.width - width - 4)
        y: from.y + 22 + height > tipLayer.height - 4 ? Math.max(4, from.y - height - 10) : from.y + 22
    }
}
