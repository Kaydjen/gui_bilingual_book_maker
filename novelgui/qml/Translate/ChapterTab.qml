pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The chapter list of Translate (7.16): no header row, the state word column grows, the current chapter is the lifted row.
// A translated row opens the reader (Enter, a double click, `Read` in its menu), as on Books. The cursor is only where the
// pointer or the arrows put it; the view-model holds no selection here.
FocusScope {
    id: tab

    property var translate: null
    property int cursor: -1
    property alias list: grid.list
    signal contextRequested(int index, var row)

    function reportVisible() {
        var a = grid.list.indexAt(10, grid.list.contentY + 4)
        var b = grid.list.indexAt(10, grid.list.contentY + grid.list.height - 4)
        if (a >= 0)
            translate.visibleRows(a, b >= 0 ? b : a + 30)
    }
    function toCurrent() {
        var r = translate.currentRow
        if (r >= 0)
            grid.list.positionViewAtIndex(Math.max(0, r - 3), ListView.Beginning)
        else
            grid.list.positionViewAtBeginning()
        reportVisible()
    }
    function step(d) {
        var n = grid.list.count
        cursor = n === 0 ? -1 : Math.max(0, Math.min(n - 1, (cursor < 0 ? (d > 0 ? -1 : n) : cursor) + d))
        if (cursor >= 0)
            grid.list.positionViewAtIndex(cursor, ListView.Contain)
    }

    DataList {
        id: grid
        objectName: "trChapters"
        anchors.fill: parent
        header: false
        model: tab.translate.chapters
        cursorIndex: tab.cursor
        columnSet: cols
        focus: true
        onRowPressed: i => tab.cursor = i
        onRowContext: i => {
            tab.cursor = i
            tab.contextRequested(i, grid.list.itemAtIndex(i))
        }
        onMoveCursor: d => tab.step(d)
        onMoveTo: w => tab.step(w === "home" ? -1000000 : 1000000)
        onRowActivated: i => tab.translate.readRow(i)
        delegate: TrRow {
            id: item
            required property int index
            translate: tab.translate
            rowIndex: item.index
            picked: Focus.byKey && item.index === tab.cursor      // lifted only while the keys move it, not after a click
        }
        Component.onCompleted: {
            list.objectName = "trChapterList"
            list.bottomMargin = 84
            list.contentYChanged.connect(tab.reportVisible)
            list.heightChanged.connect(tab.reportVisible)
        }
    }
    ColumnSet {
        id: cols
        columns: [{ key: "title", title: "", flex: 1, min: 120 }]
    }
    Connections {
        target: tab.translate
        function onScrollRequested(row) {
            grid.list.positionViewAtIndex(Math.max(0, row - 3), ListView.Beginning)
            tab.reportVisible()
        }
    }
    Connections {
        target: tab.translate.chapters
        function onModelReset() {
            tab.cursor = -1                 // the cursor is a row number: after a reload it would sit on another chapter
            Qt.callLater(tab.toCurrent)
        }
    }
    Component.onCompleted: Qt.callLater(toCurrent)
}
