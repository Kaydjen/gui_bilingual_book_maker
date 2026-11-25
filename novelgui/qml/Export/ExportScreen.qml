pragma ComponentBehavior: Bound
import QtQuick
import Novel
import Books

// The Export screen (8.7, style B): the map of the current volume in book order, one column head `Chapters` with the head box,
// pieces with a box, a mark and a `▸`, gap rows, the running job's row; the summary of the choice centred above ONE floating bar
// of two equal buttons. Everything comes from the ExportVM; this file holds only where things sit.
Item {
    id: screen

    property var exp: null
    property var app: null
    readonly property bool narrow: width < 900
    readonly property bool ready: exp.view === "ready"
    readonly property bool barShown: ready && exp.bar.length > 0
    readonly property real barY: height - 38 - 12

    function barSegments(list) {
        var out = []
        for (var i = 0; i < list.length; ++i) {
            var s = list[i]
            out.push({ text: s.text, id: s.id, tip: s.tip, kind: s.kind, busy: s.busy })
        }
        return out
    }

    Item {
        id: head
        objectName: "exHead"
        visible: screen.ready
        x: 6
        width: parent.width - 12
        height: Theme.rowHeight
        HeadBox {
            objectName: "exHeadBox"
            x: 8 + 20 + (28 - width) / 2
            anchors.verticalCenter: parent.verticalCenter
            mode: screen.exp.headState
            onToggled: screen.exp.headBox()
            TipArea { tip: screen.exp.tips.head }
        }
        AppText {
            x: 8 + 20 + 28
            height: parent.height
            text: "Chapters"
            color: Theme.dim
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
        objectName: "exMap"
        visible: screen.ready
        y: head.height
        width: parent.width
        height: parent.height - head.height
        header: false
        model: screen.exp.list
        columnSet: cols
        focus: true
        cursorIndex: screen.exp.cursor
        onRowPressed: (i, ctrl, shift) => screen.exp.rowPressed(i, ctrl, shift)
        onMoveCursor: d => screen.exp.moveCursor(d)
        onMoveTo: w => screen.exp.moveTo(w)
        onToggleCurrent: screen.exp.toggleCurrent()
        onRowActivated: i => screen.exp.activateRow(i)
        onSelectAll: screen.exp.headBox()
        delegate: ExportRow {
            id: item
            required property int index
            exp: screen.exp
            narrow: screen.narrow
            rowIndex: item.index
        }
        Component.onCompleted: {
            list.objectName = "exList"
            list.bottomMargin = 120
        }
    }
    // no current item: a ListView gives its current item the focus back, which would take it from a From / To field
    Binding {
        target: grid.list
        property: "currentIndex"
        value: -1
    }
    ColumnSet {
        id: cols
        columns: [{ key: "title", title: "", flex: 1, min: 120 }]
    }
    Skeleton {
        objectName: "exSkeleton"
        visible: screen.exp.view === "loading"
        y: head.height + 4
        x: 6
        width: parent.width - 12
        rows: Math.max(3, Math.floor(parent.height / Theme.rowHeight) - 2)
        cells: [0.1, 0.2]
        maskColor: Theme.pane
    }
    AppText {
        objectName: "exNone"
        visible: screen.exp.view === "none"
        width: parent.width
        height: parent.height
        horizontalAlignment: Text.AlignHCenter
        text: screen.exp.tips.noBook
        color: Theme.faint
    }
    AppText {
        objectName: "exBroken"
        visible: screen.exp.view === "broken"
        width: parent.width
        height: parent.height
        horizontalAlignment: Text.AlignHCenter
        text: "The book cannot be read"
        color: Theme.dim
    }

    // what goes into the file, centred above the two buttons; it is a fact, not a control
    Rectangle {
        id: sum
        objectName: "exSummary"
        visible: screen.ready && screen.exp.summaryCount !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        y: screen.barY - 28
        width: Math.min(sumCount.implicitWidth + sumRanges.implicitWidth + 24, screen.width - 48)
        height: 24
        radius: 6
        color: Theme.pane
        Row {
            id: sumRow
            anchors.centerIn: parent
            AppText {
                id: sumCount
                objectName: "exSummaryCount"
                text: screen.exp.summaryCount
                color: Theme.text
            }
            AppText {
                id: sumRanges
                objectName: "exSummaryRanges"
                width: Math.min(implicitWidth, sum.width - 24 - sumCount.width)
                elide: Text.ElideRight
                text: " " + screen.exp.summaryRanges
                color: Theme.dim
                TruncTip {}
            }
        }
        TipArea { tip: screen.exp.tips.summary }
    }
    BottomBar {
        id: bar
        objectName: "exBar"
        visible: screen.barShown
        anchors.horizontalCenter: parent.horizontalCenter
        y: screen.barY
        segments: screen.barSegments(screen.exp.bar)
        segWidth: screen.narrow ? 150 : 170
        onActivated: (i, id) => screen.exp.act(id)
    }
    Shortcut {
        sequences: ["Escape"]
        enabled: screen.visible && screen.exp.busy !== "" && screen.app.panel === ""
        onActivated: screen.exp.escape()
    }
}
