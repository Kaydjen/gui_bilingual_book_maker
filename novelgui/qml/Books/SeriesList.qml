pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The left pane of Books: series (and the books of the selected one), `+` bottom-left (a spinner while a book is copied in),
// red `Add book` in the middle when the library has no series. Both fades; empty space under the last row.
Item {
    id: pane

    property var books: null
    property alias list: view
    signal addRequested()
    signal menuRequested(int index, Item row, real x, real y)

    readonly property bool noSeries: books.view === "empty" && books.seriesList.rowCount() === 0

    Rectangle {
        anchors.fill: parent
        radius: Theme.rPane
        color: Theme.s1
    }
    ListView {
        id: view
        objectName: "seriesList"
        anchors.fill: parent
        anchors.topMargin: 6
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        bottomMargin: 64
        model: pane.books.seriesList
        delegate: SeriesRow {
            id: item
            required property int index
            books: pane.books
            rowIndex: item.index
            onMenuRequested: (x, y) => pane.menuRequested(item.index, item, x, y)
        }
    }
    ScrollAssist {
        objectName: "seriesScroll"
        flickable: view
    }
    Fades {
        flickable: view
        color: Theme.s1
    }
    Pill {
        objectName: "addBookRed"
        visible: pane.noSeries && !pane.books.libraryLoading
        anchors.centerIn: parent
        text: "Add book"
        kind: "accent"
        onClicked: pane.addRequested()
    }
    Sat {
        objectName: "plusButton"
        visible: !pane.noSeries || pane.books.adding
        opacity: pane.books.editKind !== "" ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
        x: 12
        y: parent.height - height - 12
        text: pane.books.adding ? "" : "+"
        tip: pane.books.adding ? pane.books.tips.adding : pane.books.tips.plus
        onClicked: if (!pane.books.adding) pane.addRequested()
        Spinner {
            objectName: "addSpinner"
            visible: pane.books.adding
            anchors.centerIn: parent
            size: 18
            active: pane.books.adding
        }
    }
}
