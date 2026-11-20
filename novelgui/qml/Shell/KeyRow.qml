pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A key row: the masked key, its state word only when it needs attention (`invalid` is red), the same empty right slot as
// the model arrows, `✕` on hover.
Item {
    id: row

    required property int index
    required property string masked
    required property string word
    required property bool red
    required property string tip
    property var tips: ({})
    signal removeClicked()

    width: ListView.view ? ListView.view.width : 300
    height: 30

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Theme.rRow
        color: Theme.rowHover
        visible: hover.hovered
    }
    AppText {
        objectName: "keyMask" + row.index
        x: 12
        height: parent.height
        text: row.masked
        font.family: "Consolas"
        color: Theme.text
    }
    AppText {
        objectName: "keyWord" + row.index
        anchors.right: parent.right
        anchors.rightMargin: 12 + 40 + 24
        height: parent.height
        text: row.word
        color: row.red ? Theme.accent : Theme.dim
        TipArea { tip: row.tip }
    }
    Item {
        objectName: "keyRemove" + row.index
        anchors.right: parent.right
        anchors.rightMargin: 6
        width: 24
        height: parent.height
        visible: hover.hovered
        AppText {
            anchors.centerIn: parent
            text: "✕"
            font.pixelSize: 12
            color: xHover.hovered ? Theme.bright : Theme.dim
        }
        HoverHandler { id: xHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: row.removeClicked() }
        TipArea { tip: row.tips.keyRemove }
    }
    HoverHandler { id: hover }
}
