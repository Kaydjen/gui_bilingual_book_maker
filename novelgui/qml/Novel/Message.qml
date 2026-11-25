pragma ComponentBehavior: Bound
import QtQuick

// A message (9.12): the fact as a dim line centred above, its verbs in the style-B bar under it. `fact` is a list of
// parts {text, kind} (kind "" = dim, "n" = normal, "red" = a problem, "bright"); `progress` >= 0 adds a thin line.
Item {
    id: msg

    property var fact: []
    property var verbs: []
    property real progress: -1
    signal verbActivated(int index, string id)

    implicitWidth: Math.max(line.width, bar.width)
    implicitHeight: col.implicitHeight

    function html() {
        var colors = { "": Theme.dim, "n": Theme.text, "red": Theme.accent, "bright": Theme.bright }
        var out = ""
        for (var i = 0; i < fact.length; ++i)
            out += "<font color='" + colors[fact[i].kind || ""] + "'>" + fact[i].text.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</font>"
        return out
    }

    Column {
        id: col
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 8

        Item {
            id: line
            objectName: "messageLine"
            anchors.horizontalCenter: parent.horizontalCenter
            width: text.implicitWidth + 24
            height: text.implicitHeight + 8

            BorderImage {
                x: -34
                y: -34
                width: parent.width + 68
                height: parent.height + 68
                source: Theme.assetsBase + "halo.png"
                border { left: 48; right: 48; top: 48; bottom: 48 }
            }
            Rectangle {
                anchors.fill: parent
                radius: 6
                color: Theme.pane
            }
            AppText {
                id: text
                anchors.centerIn: parent
                textFormat: Text.StyledText
                text: msg.html()
            }
        }
        Rectangle {
            visible: msg.progress >= 0
            anchors.horizontalCenter: parent.horizontalCenter
            width: line.width
            height: 2
            color: Theme.s3
            Rectangle {
                width: parent.width * Math.min(1, Math.max(0, msg.progress))
                height: 2
                color: Theme.dim
            }
        }
        BottomBar {
            id: bar
            objectName: msg.objectName + "Bar"
            visible: msg.verbs.length > 0
            anchors.horizontalCenter: parent.horizontalCenter
            segments: msg.verbs
            onActivated: (i, id) => msg.verbActivated(i, id)
        }
    }
}
