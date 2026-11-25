pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Problems tab (7.16): failed blocks and check findings in one list (the kind is the Reason). A click selects a row (a second
// click on it closes); the row editor under the pane works on the selected one.
FocusScope {
    id: tab

    property var translate: null
    readonly property int cursor: translate.editor.open === true ? translate.editor.index : -1
    property alias list: grid.list

    DataList {
        id: grid
        objectName: "trProblems"
        anchors.fill: parent
        header: true
        model: tab.translate.problemsModel
        cursorIndex: -1
        columnSet: cols
        focus: true
        onRowPressed: i => tab.translate.selectProblem(i)
        onMoveCursor: d => tab.translate.selectProblem(Math.max(0, Math.min(grid.list.count - 1, tab.cursor + d)))
        onRowActivated: i => tab.translate.selectProblem(i)
        delegate: RowBase {
            id: row
            required property int index
            required property string title
            required property string block
            required property string source
            required property string reason
            required property string kind
            required property string detail
            required property var model
            rowIndex: row.index
            selected: row.model.selected === true
            Cell {
                objectName: "problemChapter" + row.index
                columns: cols
                column: "chapter"
                text: row.title
                color: Theme.text
            }
            Cell {
                columns: cols
                column: "block"
                align: "right"
                rightPadding: 14
                text: row.block
                color: Theme.dim
            }
            Cell {
                objectName: "problemSource" + row.index
                columns: cols
                column: "source"
                text: row.source
                color: row.selected ? Theme.bright : Theme.text
            }
            Cell {
                objectName: "problemReason" + row.index
                columns: cols
                column: "reason"
                text: row.reason
                color: Theme.dim
                TipArea { tip: row.kind === "failed" ? tab.translate.tips.problemFailed : row.detail }
            }
        }
        Component.onCompleted: {
            list.objectName = "trProblemList"
            list.bottomMargin = 84
        }
    }
    ColumnSet {
        id: cols
        columns: [{ key: "chapter", title: "Chapter", width: 190, min: 120 },
                  { key: "block", title: "Block", width: 64, align: "right", min: 50 },
                  { key: "source", title: "Source", flex: 1, min: 120 },
                  { key: "reason", title: "Reason", width: 130, min: 80 }]
    }
}
