pragma ComponentBehavior: Bound
import QtQuick
import Novel

// ONE panel for one or many files (5.1-5.4, 9.11): rows File | Series | label (or note) | ✕ on hover. The size is fixed when the
// panel opens; the rows scroll inside. The Series box is a drop-down of the library's series with their book counts, typing
// filters, a name that is not in the list makes the first entry `+ New series <name>`.
Panel {
    id: panel

    property var add: null
    readonly property real rowH: 36
    readonly property real headH: 28

    cardItem.objectName: "addCard"
    closeButton.objectName: "addClose"
    actionButton.objectName: "addAction"
    title: add.title
    closeText: "Cancel"
    actionText: add.actionText
    actionEnabled: add.canAdd
    panelWidth: 620
    onAccepted: add.accept()
    onCloseRequested: add.close()

    Item {
        width: parent.width
        height: panel.headH + panel.add.rowsShown * panel.rowH + 8

        Rectangle {
            anchors.fill: parent
            radius: 8
            color: Theme.field
            border.width: 1
            border.color: Theme.fieldLine
        }
        Row {
            x: 10
            height: panel.headH
            AppText { width: parent.parent.width * 0.38; height: parent.height; text: "File"; color: Theme.dim }
            AppText { width: parent.parent.width * 0.34; height: parent.height; text: "Series"; color: Theme.dim }
        }
        ListView {
            id: list
            objectName: "addRows"
            y: panel.headH
            width: parent.width
            height: parent.height - panel.headH - 4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: panel.add.rows
            delegate: AddRow {
                id: line
                required property int index
                add: panel.add
                width: list.width
                height: panel.rowH
                rowIndex: line.index
                onPickSeries: (anchorItem, i) => {
                    picker.rowIndex = i
                    picker.entries = panel.add.entries(i, "")
                    picker.openUnder(anchorItem)
                }
            }
        }
        Fades {
            flickable: list
            color: Theme.field
            topOffset: panel.headH
            bottomHeight: 30
            topHeight: 20
        }
    }
    Component.onCompleted: add.openChanged.connect(sync)
    function sync() {
        if (add.isOpen)
            open()
        else
            close()
    }
    DropDown {
        id: picker
        objectName: "seriesPicker"
        parent: panel
        property int rowIndex: -1
        filtering: true
        placeholder: "Series name"
        cardWidth: 280
        z: 900
        onFilterChanged: text => entries = panel.add.entries(rowIndex, text)
        onPicked: (i, id) => panel.add.setSeries(rowIndex, id)
    }
}
