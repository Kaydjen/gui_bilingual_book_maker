pragma ComponentBehavior: Bound
import QtQuick

// The table base: a pane with a header row (shared ColumnSet, own splitters for drag-resize) and a virtual ListView of row
// delegates. Selection lives in the view-model (RowSelection): this item only reports the pointer and the keys and shows the
// roles `selected` / `current` the model gives. Delegate: a Component built on RowBase; the default shows each column's key as text.
FocusScope {
    id: table

    property var model: null
    property ColumnSet columnSet: ColumnSet {}
    property Component delegate: defaultRow
    property alias list: listView
    property alias contentItem: listView.contentItem
    property int cursorIndex: -1
    property bool header: true
    property real headerHeight: Theme.rowHeight
    property real pageRows: Math.max(1, Math.floor(listView.height / Theme.rowHeight) - 1)
    property string sortKey: ""

    signal rowPressed(int index, bool ctrl, bool shift)
    signal rowContext(int index)
    signal rowDragged(int index)
    signal rowActivated(int index)
    signal moveCursor(int delta, bool extend)
    signal moveTo(string where, bool extend)
    signal selectAll()
    signal toggleCurrent()
    signal copyRequested()
    signal deleteRequested()
    signal headerClicked(string key)

    function pressedAt(index, button, ctrl, shift) {
        forceActiveFocus()
        if (button === Qt.RightButton)
            rowContext(index)
        else
            rowPressed(index, ctrl, shift)
    }
    function draggedTo(p) {
        var i = listView.indexAt(p.x, Math.max(listView.contentY + 1, Math.min(p.y, listView.contentY + listView.height - 2)))
        if (i >= 0)
            rowDragged(i)
    }
    onCursorIndexChanged: if (cursorIndex >= 0) listView.positionViewAtIndex(cursorIndex, ListView.Contain)

    Rectangle {
        anchors.fill: parent
        radius: Theme.rPane
        color: Theme.pane
        Rectangle {
            x: Theme.rPane
            width: parent.width - 2 * Theme.rPane
            height: 1
            color: Theme.hairline
        }
    }
    Item {
        id: head
        objectName: "tableHeader"
        visible: table.header
        x: 6
        width: parent.width - 12
        height: table.header ? table.headerHeight : 0

        Row {
            x: 8
            height: parent.height
            Repeater {
                model: table.columnSet.columns
                delegate: Item {
                    id: hc
                    required property var modelData
                    readonly property real startWidth: table.columnSet.widthOf(modelData.key)
                    width: table.columnSet.widthOf(modelData.key)
                    height: head.height

                    AppText {
                        objectName: "headCell_" + hc.modelData.key
                        width: parent.width
                        height: parent.height
                        rightPadding: 8
                        elide: Text.ElideRight
                        text: hc.modelData.title
                        color: table.sortKey === hc.modelData.key ? Theme.text : Theme.dim
                        horizontalAlignment: hc.modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                        TapHandler { onTapped: table.headerClicked(hc.modelData.key) }
                    }
                    Item {
                        id: splitter
                        objectName: "splitter_" + hc.modelData.key
                        visible: hc.modelData.fixed !== true
                        x: parent.width - 4
                        width: 8
                        height: parent.height
                        property real base: 0
                        HoverHandler { id: sh; cursorShape: Qt.SizeHorCursor }
                        Rectangle {
                            visible: sh.hovered || drag.active
                            x: 3
                            y: 6
                            width: 1
                            height: parent.height - 12
                            color: Theme.s4
                        }
                        DragHandler {
                            id: drag
                            target: null
                            yAxis.enabled: false
                            onActiveChanged: if (active) splitter.base = hc.width
                            onTranslationChanged: if (active) table.columnSet.resize(hc.modelData.key, splitter.base + translation.x)
                        }
                    }
                }
            }
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.rowLine
        }
    }
    ListView {
        id: listView
        objectName: "tableList"
        property var owner: table
        anchors.top: head.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.topMargin: 2
        clip: true
        reuseItems: true
        cacheBuffer: 200
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: false
        model: table.model
        delegate: table.delegate
        onWidthChanged: table.columnSet.available = width - 12 - 16
        Component.onCompleted: table.columnSet.available = width - 12 - 16
    }
    ScrollAssist {
        objectName: "tableScroll"
        flickable: listView
    }
    Fades {
        flickable: listView
        topOffset: table.header ? table.headerHeight + 2 : 0
    }

    Component {
        id: defaultRow
        RowBase {
            id: row
            required property int index
            required property var model
            rowIndex: index
            selected: model.selected === true
            current: model.current === true
            Repeater {
                model: table.columnSet.columns
                delegate: Cell {
                    required property var modelData
                    columns: table.columnSet
                    column: modelData.key
                    align: modelData.align || "left"
                    text: row.model[modelData.key] === undefined ? "" : String(row.model[modelData.key])
                    color: row.selected || row.current ? Theme.bright : Theme.text
                }
            }
        }
    }

    // key -> [signal, argument, needs Ctrl, argument counts pages]
    readonly property var navKeys: ({
        [Qt.Key_Up]: ["move", -1, false, false], [Qt.Key_Down]: ["move", 1, false, false],
        [Qt.Key_PageUp]: ["move", -1, false, true], [Qt.Key_PageDown]: ["move", 1, false, true],
        [Qt.Key_Home]: ["home", 0, false, false], [Qt.Key_End]: ["end", 0, false, false],
        [Qt.Key_Space]: ["toggle", 0, false, false], [Qt.Key_Delete]: ["delete", 0, false, false],
        [Qt.Key_Return]: ["activate", 0, false, false], [Qt.Key_Enter]: ["activate", 0, false, false],
        [Qt.Key_F2]: ["activate", 0, false, false], [Qt.Key_A]: ["all", 0, true, false],
        [Qt.Key_C]: ["copy", 0, true, false]
    })

    function dispatch(a, shift) {
        switch (a[0]) {
        case "move": moveCursor(a[1] * (a[3] ? pageRows : 1), shift); break
        case "home": case "end": moveTo(a[0], shift); break
        case "toggle": toggleCurrent(); break
        case "delete": deleteRequested(); break
        case "activate": if (cursorIndex >= 0) rowActivated(cursorIndex); break
        case "all": selectAll(); break
        case "copy": copyRequested(); break
        }
    }
    Keys.onPressed: event => {
        var a = navKeys[event.key]
        var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
        event.accepted = a !== undefined && (!a[2] || ctrl)
        if (event.accepted) {
            dispatch(a, (event.modifiers & Qt.ShiftModifier) !== 0)
            Focus.byKey = true
        }
    }
}
