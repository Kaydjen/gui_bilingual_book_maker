pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A chapter row: box, number, title, state bar. The roles come from the ChapterModel (8 per row).
RowBase {
    id: row

    property var books: null
    property ColumnSet columns: null
    required property string no
    required property string title
    required property string kind
    required property string stateText
    required property real fraction
    required property real failed
    required property var model
    readonly property bool toc: kind === "toc"

    leftPad: 8
    dimmed: toc
    selected: model.selected === true
    current: Focus.byKey && model.current === true      // the cursor is lifted only while the keys move it: an unticked row looks unticked

    Item {
        width: row.columns.widthOf("box")
        height: Theme.rowHeight
        CheckMark {
            visible: !row.toc
            anchors.centerIn: parent
            checked: row.selected
            hot: row.hovered
        }
    }
    AppText {
        visible: row.books.showNumbers
        width: row.columns.widthOf("no")
        height: Theme.rowHeight
        text: row.no
        color: row.selected ? Theme.bright : Theme.dim
    }
    AppText {
        objectName: "chapterTitle"
        width: row.columns.widthOf("title")
        height: Theme.rowHeight
        rightPadding: 8
        elide: Text.ElideRight
        text: row.title
        color: row.toc ? Theme.faint : (row.selected || row.current ? Theme.bright : Theme.text)
        TruncTip {}
    }
    Item {
        width: row.columns.widthOf("state")
        height: Theme.rowHeight
        Rectangle {
            visible: !row.toc
            x: 0
            y: 13
            width: parent.width - 28
            height: 3
            radius: 1.5
            color: Theme.s3
            Rectangle {
                width: parent.width * Math.min(1, row.fraction)
                height: parent.height
                radius: 1.5
                color: Theme.bright
            }
            Rectangle {
                x: parent.width * Math.min(1, row.fraction)
                width: parent.width * Math.min(1 - Math.min(1, row.fraction), row.failed)
                height: parent.height
                radius: 1.5
                color: Theme.dim
            }
        }
        TipArea { tip: row.stateText }
    }
}
