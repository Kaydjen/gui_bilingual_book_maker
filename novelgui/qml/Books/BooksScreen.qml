pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Books screen (4.1-4.7): the series list on the left, the chapter table (or its empty / damaged / missing state) on the
// right, the capsule or the message floating at the bottom of the chapter area. Menus open here; the Add and Move panels are
// raised by the shell.
Item {
    id: screen

    property var books: null
    property var app: null
    readonly property int leftWidth: Math.max(250, Math.min(400, Math.round(width * 0.37)))

    SeriesList {
        id: pane
        objectName: "seriesPane"
        x: 0
        y: 0
        width: screen.leftWidth
        height: parent.height
        books: screen.books
        onAddRequested: screen.books.chooseFiles()
        onMenuRequested: (i, row, x, y) => {
            var p = row.mapToItem(menu, x, y)
            menu.rowIndex = i
            menu.items = screen.books.menuFor(i)
            menu.openAt(p.x - 150, p.y)
        }
    }
    Item {
        id: right
        objectName: "chapterPane"
        x: pane.x + pane.width + 16
        y: 0
        width: parent.width - x
        height: parent.height

        ChapterList {
            id: chapters
            objectName: "chapterList"
            anchors.fill: parent
            visible: screen.books.view === "chapters"
            books: screen.books
            onContextRequested: (i, row, x, y) => {
                var p = row.mapToItem(menu, x, y)
                menu.rowIndex = -1 - i
                menu.items = screen.books.chapterMenu(i)
                menu.openAt(p.x, p.y)
            }
        }
        Rectangle {
            visible: screen.books.view !== "chapters"
            anchors.fill: parent
            radius: Theme.rPane
            color: Theme.s1
        }
        Column {
            objectName: "noBooks"
            visible: screen.books.view === "nobooks"
            anchors.centerIn: parent
            spacing: 10
            Pill {
                objectName: "addBookNoBooks"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Add book"
                kind: "accent"
                onClicked: screen.books.chooseFiles()
            }
            AppText {
                objectName: "noBooksText"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "No book in this series yet"
                color: Theme.dim
            }
        }
        Column {
            objectName: "unavailable"
            visible: screen.books.view === "broken" || screen.books.view === "missing"
            anchors.centerIn: parent
            spacing: 8
            AppText {
                objectName: "unavailableTitle"
                anchors.horizontalCenter: parent.horizontalCenter
                text: screen.books.view === "missing" ? "This book's file is not there" : "This series cannot be opened"
                color: Theme.dim
            }
            AppText {
                objectName: "unavailableReason"
                anchors.horizontalCenter: parent.horizontalCenter
                text: screen.books.view === "missing" ? screen.books.missingName : screen.books.reason
                color: Theme.text
            }
            Pill {
                objectName: "openFolder"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Open folder"
                kind: "flat"
                onClicked: screen.books.view === "missing" ? screen.books.openBooksFolder() : screen.books.openCurrentFolder()
            }
        }
        Capsule {
            objectName: "capsuleBox"
            visible: screen.books.capsuleVisible && screen.books.view === "chapters" && !hasNotice
            readonly property bool hasNotice: screen.books.notice.fact !== undefined
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            books: screen.books
        }
        Message {
            id: notice
            objectName: "notice"
            visible: screen.books.notice.fact !== undefined
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            fact: screen.books.notice.fact || []
            verbs: (screen.books.notice.verbs || []).map(v => ({ text: v.text, id: v.id, kind: "main", tip: v.text === "Undo" ? screen.books.tips.undo : "" }))
            onVerbActivated: (i, id) => screen.books.undo()
        }
    }
    BusyLine {
        objectName: "libraryBusy"
        visible: screen.books.libraryLoading
        width: parent.width
        active: visible
    }
    Menu {
        id: menu
        objectName: "booksMenu"
        property int rowIndex: -1
        onPicked: (i, id) => rowIndex >= 0 ? screen.books.menuPicked(rowIndex, id) : screen.books.chapterPicked(-1 - rowIndex, id)
    }
}
