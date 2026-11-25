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

    // a press outside the text input being typed in takes the focus from it, so a field commits when ANY control is pressed
    function releaseInput(at) {
        var w = Window.window
        var f = w ? (w.activeFocusItem as TextInput) : null       // a TextEdit (several lines) keeps its focus, it has no commit
        if (!f)
            return
        var p = f.mapFromItem(null, at.x, at.y)
        var q = f.parent ? f.parent.mapFromItem(null, at.x, at.y) : p
        if ((p.x >= 0 && p.y >= 0 && p.x < f.width && p.y < f.height) || (f.parent && q.x >= 0 && q.y >= 0 && q.x < f.parent.width && q.y < f.parent.height))
            return
        f.focus = false
    }

    PointHandler {
        acceptedButtons: Qt.AllButtons
        onActiveChanged: {
            Tips.dismiss()
            Focus.byKey = false
            if (active)
                tipLayer.releaseInput(point.scenePosition)
        }
    }

    Tip {
        id: bubble
        objectName: "tip"
        visible: Tips.shown
        text: Tips.text
        facts: Tips.facts
        onCard: Theme.onPanel(Tips.owner)
        readonly property point from: tipLayer.mapFromItem(null, Tips.at.x, Tips.at.y)
        x: tipLayer.clamp(from.x + 14, 4, tipLayer.width - width - 4)
        y: from.y + 22 + height > tipLayer.height - 4 ? Math.max(4, from.y - height - 10) : from.y + 22
    }
}
