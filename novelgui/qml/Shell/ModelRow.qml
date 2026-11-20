pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A model row: the name (double-click edits it in place), a state word (`not found` dim, `no free quota` red), `↑ ↓` on
// hover (no ↑ on the first, no ↓ on the last), `✕` at the far right.
Item {
    id: row

    required property int index
    required property string name
    required property string word
    required property bool red
    required property bool canUp
    required property bool canDown
    required property string tip
    property var tips: ({})
    signal moveClicked(int delta)
    signal removeClicked()
    signal renamed(string text)

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
        objectName: "modelName" + row.index
        visible: !edit.visible
        x: 12
        width: parent.width - 12 - 12 - 40 - 24 - word.width - 8
        height: parent.height
        elide: Text.ElideRight
        text: row.name
        color: row.word === "not found" ? Theme.dim : Theme.text
        TapHandler {
            acceptedButtons: Qt.LeftButton
            onDoubleTapped: {
                edit.visible = true
                edit.input.forceActiveFocus()
            }
        }
        TipArea { tip: row.tips.modelEdit }
    }
    Field {
        id: edit
        objectName: "modelEdit" + row.index
        visible: false
        x: 6
        y: 1
        width: parent.width - 100
        height: 28
        value: row.name
        onCommitted: text => {
            row.renamed(text)
            edit.visible = false
        }
        onEditingChanged: if (!editing) edit.visible = false
    }
    AppText {
        id: word
        objectName: "modelWord" + row.index
        anchors.right: parent.right
        anchors.rightMargin: 12 + 40 + 24
        height: parent.height
        text: row.word
        color: row.red ? Theme.accent : Theme.dim
        TipArea { tip: row.tip }
    }
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 12 + 24
        width: 40
        height: parent.height
        visible: hover.hovered
        Repeater {
            model: [{ "glyph": "↑", "delta": -1 }, { "glyph": "↓", "delta": 1 }]
            delegate: Item {
                id: arrow
                required property var modelData
                readonly property bool usable: modelData.delta < 0 ? row.canUp : row.canDown
                width: 20
                height: row.height
                AppText {
                    anchors.centerIn: parent
                    visible: arrow.usable
                    text: arrow.modelData.glyph
                    color: arrowHover.hovered ? Theme.bright : Theme.dim
                }
                HoverHandler { id: arrowHover; enabled: arrow.usable; cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: arrow.usable; onTapped: row.moveClicked(arrow.modelData.delta) }
                TipArea { tip: arrow.usable ? (arrow.modelData.delta < 0 ? row.tips.modelUp : row.tips.modelDown) : "" }
            }
        }
    }
    Item {
        objectName: "modelRemove" + row.index
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
        TipArea { tip: row.tips.modelRemove }
    }
    HoverHandler { id: hover }
}
