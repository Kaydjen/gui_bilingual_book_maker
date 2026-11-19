pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The chapter table (4.5, 4.7): a head box (none -> all, some or all -> none), `No.` only when the titles carry no numbers,
// Title, State as a thin bar. A click on a box or a row toggles the row, Shift takes a range. A digit typed on the focused list
// opens the range field of the capsule. Shimmering rows while the book is read (after 0.3 s).
FocusScope {
    id: table

    property var books: null
    property alias list: grid.list
    signal contextRequested(int index, Item row, real x, real y)

    function reportVisible() {
        var a = grid.list.indexAt(10, grid.list.contentY + 4)
        var b = grid.list.indexAt(10, grid.list.contentY + grid.list.height - 4)
        if (a >= 0)
            books.visibleRows(a, b >= 0 ? b : a + 30)
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.rPane
        color: Theme.s1
    }
    Item {
        id: head
        objectName: "chapterHead"
        x: 6
        width: parent.width - 12
        height: Theme.rowHeight
        HeadBox {
            objectName: "headBox"
            x: 8 + (34 - width) / 2
            anchors.verticalCenter: parent.verticalCenter
            mode: table.books.headState
            onToggled: table.books.headBox()
            TipArea { tip: table.books.tips.head }
        }
        Row {
            x: 8 + 34
            height: parent.height
            AppText {
                objectName: "headNo"
                visible: table.books.showNumbers
                width: cols.widthOf("no")
                height: parent.height
                text: "No."
                color: Theme.dim
            }
            AppText {
                width: cols.widthOf("title")
                height: parent.height
                text: "Title"
                color: Theme.dim
            }
            AppText {
                width: cols.widthOf("state")
                height: parent.height
                text: "State"
                color: Theme.dim
            }
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.rowLine
        }
    }
    DataList {
        id: grid
        objectName: "chapterTable"
        y: head.height
        width: parent.width
        height: parent.height - head.height
        header: false
        model: table.books.chapters
        cursorIndex: table.books.cursor
        columnSet: cols
        focus: true
        onRowPressed: (i, ctrl, shift) => table.books.rowPressed(i, ctrl, shift)
        onRowContext: i => table.contextRequested(i, grid.list.itemAtIndex(i), 200, 15)
        onRowDragged: i => table.books.rowDragged(i)
        onMoveCursor: (d, ext) => table.books.moveCursor(d, ext)
        onMoveTo: (w, ext) => table.books.moveTo(w, ext)
        onSelectAll: table.books.selectAll()
        onToggleCurrent: table.books.toggleCurrent()
        onRowActivated: i => table.books.activate(i)
        onDeleteRequested: table.books.clearSelection()
        delegate: ChapterRow {
            id: item
            required property int index
            books: table.books
            columns: cols
            rowIndex: item.index
        }
        Keys.onPressed: event => {
            if (event.text.length === 1 && event.text >= "0" && event.text <= "9" && !(event.modifiers & Qt.ControlModifier)) {
                table.books.beginTyping(event.text)
                event.accepted = true
            }
        }
        Component.onCompleted: {
            list.bottomMargin = 84
            list.contentYChanged.connect(table.reportVisible)
            list.heightChanged.connect(table.reportVisible)
        }
    }
    Connections {
        target: table.books
        function onScrollRequested(i) {
            grid.list.positionViewAtIndex(Math.max(0, i - 3), ListView.Beginning)
            table.reportVisible()
        }
    }
    ColumnSet {
        id: cols
        columns: table.books.showNumbers
            ? [{ key: "box", title: "", width: 34, fixed: true }, { key: "no", title: "No.", width: 64, fixed: true },
               { key: "title", title: "Title", flex: 1, min: 120 }, { key: "state", title: "State", width: 170, fixed: true }]
            : [{ key: "box", title: "", width: 34, fixed: true }, { key: "title", title: "Title", flex: 1, min: 120 },
               { key: "state", title: "State", width: 170, fixed: true }]
    }
    Skeleton {
        objectName: "chapterSkeleton"
        visible: table.books.chaptersLoading
        y: head.height + 4
        x: 6
        width: parent.width - 12
        rows: Math.max(3, Math.floor((parent.height - head.height) / Theme.rowHeight) - 1)
        cells: [0.04, 0.4, 0.12]
        maskColor: Theme.s1
    }
}
