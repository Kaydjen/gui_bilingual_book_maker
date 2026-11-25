pragma ComponentBehavior: Bound
import QtQuick
import Novel

// `Move Book 1 to series…` (4.7): the other series as rows, `Cancel | Move`. Only for a book with nothing translated.
Panel {
    id: panel

    property var books: null
    property string chosen: ""

    cardItem.objectName: "moveCard"
    closeButton.objectName: "moveClose"
    actionButton.objectName: "moveAction"
    title: books.moveTitle
    closeText: "Cancel"
    actionText: "Move"
    actionEnabled: chosen !== ""
    panelWidth: 380
    onAccepted: books.moveBook(chosen)
    onCancelled: chosen = ""
    onCloseRequested: books.closeMove()

    Item {
        width: parent.width
        height: Math.min(6, Math.max(1, panel.books.moveTargets.length)) * 32 + 8
        Rectangle {
            anchors.fill: parent
            radius: 8
            color: Theme.field
            border.width: 1
            border.color: Theme.fieldLine
        }
        ListView {
            objectName: "moveRows"
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: panel.books.moveTargets
            delegate: Item {
                id: entry
                required property var modelData
                width: ListView.view.width
                height: 32
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.rRow
                    color: panel.chosen === entry.modelData.id ? Theme.rowSelected : (tHover.hovered ? Theme.rowHover : "transparent")
                }
                Rectangle {
                    visible: panel.chosen === entry.modelData.id
                    x: 3
                    y: 8
                    width: 2
                    height: 16
                    radius: 1
                    color: Theme.bright
                }
                AppText {
                    objectName: "moveRow_" + entry.modelData.text
                    x: 14
                    height: parent.height
                    text: entry.modelData.text
                    color: panel.chosen === entry.modelData.id ? Theme.bright : Theme.text
                }
                HoverHandler { id: tHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: panel.chosen = entry.modelData.id }
            }
        }
    }
    Component.onCompleted: books.movePanelChanged.connect(sync)
    function sync() {
        if (books.moveOpen) {
            chosen = ""
            open()
        } else {
            close()
        }
    }
}
