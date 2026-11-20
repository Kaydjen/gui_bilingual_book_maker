pragma ComponentBehavior: Bound
import QtQuick
import Novel

// One row of the left list: a series (name, a dim book count when collapsed, the language, `•••`) or a book of the selected
// series (indented, on a thin guide line). A row being renamed shows a field in place; a damaged series is dim with `!`.
RowBase {
    id: row

    property var books: null
    required property string kind
    required property string key
    required property string text
    required property string tail
    required property int count
    required property string mode
    required property bool editing
    property bool dotsShown: hovered || current
    readonly property bool isBook: kind === "book"
    readonly property bool broken: mode === "broken" || mode === "brokenSelected"
    signal menuRequested(real x, real y)

    current: mode === "selected" || mode === "brokenSelected" || editing
    opacity: books.editKind !== "" && !editing ? 0.38 : 1
    dimmed: broken
    selected: false
    leftPad: 0

    Item {
        width: row.width - 12
        height: Theme.rowHeight

        Rectangle {
            visible: row.isBook
            x: 14
            width: 1
            height: parent.height
            color: Theme.s4
        }
        AppText {
            id: name
            objectName: "seriesName"
            visible: !row.editing
            x: row.isBook ? 28 : 12
            width: Math.min(implicitWidth, parent.width - x - 60)
            height: parent.height
            elide: Text.ElideRight
            text: row.text
            color: row.isBook ? (row.mode === "selected" ? Theme.bright : Theme.dim)
                              : (row.mode === "selected" || row.mode === "parent" ? Theme.bright : Theme.text)
        }
        AppText {
            visible: !row.editing && row.count > 0
            x: name.x + name.width + 6
            height: parent.height
            text: row.count
            color: Theme.faint
            font.pixelSize: Theme.fontSmall
        }
        AppText {
            visible: !row.editing && !row.dotsShown
            anchors.right: parent.right
            anchors.rightMargin: 12
            height: parent.height
            text: row.broken ? "!" : row.tail
            color: row.broken ? Theme.dim : Theme.faint
            font.weight: row.broken ? Font.Bold : Font.Normal
        }
        AppText {
            objectName: "seriesDots" + row.rowIndex
            visible: !row.editing && row.dotsShown && !row.broken
            anchors.right: parent.right
            anchors.rightMargin: 12
            height: parent.height
            text: "•••"
            font.bold: true
            font.letterSpacing: -1
            color: dots.hovered ? Theme.bright : Theme.dim
            HoverHandler { id: dots }
            TapHandler { onTapped: row.menuRequested(row.x + row.width - 20, row.y + row.height) }
            TipArea { tip: row.isBook ? row.books.tips.book : row.books.tips.series }
        }
        Loader {
            id: editor
            active: row.editing
            x: row.isBook ? 22 : 4
            y: 1
            width: parent.width - x - 4
            height: Theme.rowHeight - 2
            sourceComponent: Field {
                objectName: "renameField"
                value: row.books.editValue
                keepOpen: true
                validate: t => { invalidTip = row.books.renameProblem(t); return invalidTip === "" }
                onCommitted: t => row.books.commitRename(t)
                onEditingChanged: if (!editing) row.books.cancelRename()
                Component.onCompleted: input.forceActiveFocus()
            }
        }
    }
    TapHandler {
        enabled: !dots.hovered                  // a tap on `•••` opens the menu only, it does not also pick the row
        acceptedButtons: Qt.LeftButton
        onTapped: if (!row.editing) row.books.pickRow(row.rowIndex)
        onDoubleTapped: if (!row.editing && !row.broken) row.books.startRename(row.isBook ? "book" : "series", row.key)
    }
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: if (!row.editing) row.menuRequested(row.width / 2, row.y + row.height / 2)
    }
}
