pragma ComponentBehavior: Bound
import QtQuick
import Novel

// One file of the Add panel: its name, the Series box (a drop-down; `+` marks a new series), the label the file will get
// (or the note: `protected`, the reason a file cannot be read), and `✕` on hover that leaves the file out.
Item {
    id: line

    property var add: null
    property int rowIndex: -1
    required property string file
    required property string series
    required property bool isNew
    required property string label
    required property string note
    required property string status
    readonly property bool usable: status === "ok"
    signal pickSeries(Item anchorItem, int index)

    HoverHandler { id: hover }
    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        radius: Theme.rRow
        color: hover.hovered ? Theme.rowHover : "transparent"
    }
    AppText {
        objectName: "addFile" + line.rowIndex
        x: 10
        width: line.width * 0.38 - 14
        height: parent.height
        elide: Text.ElideMiddle
        text: line.file
        color: line.usable ? Theme.text : Theme.faint
        TruncTip {}
    }
    Inset {
        id: box
        objectName: "addSeries" + line.rowIndex
        visible: line.usable
        x: line.width * 0.38
        anchors.verticalCenter: parent.verticalCenter
        width: line.width * 0.34 - 12
        height: 28
        edge: boxHover.hovered ? Theme.fieldFocus : Theme.s4
        AppText {
            objectName: "addSeriesText" + line.rowIndex
            x: 10
            width: parent.width - 30
            height: parent.height
            elide: Text.ElideRight
            text: (line.isNew ? "+ " : "") + line.series
            color: Theme.bright
        }
        AppText {
            anchors.right: parent.right
            anchors.rightMargin: 10
            height: parent.height
            text: "▾"
            font.pixelSize: 9
            color: Theme.dim
        }
        HoverHandler { id: boxHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: line.pickSeries(box, line.rowIndex) }
        TipArea { tip: line.add.seriesTip(line.rowIndex) }
    }
    AppText {
        objectName: "addLabel" + line.rowIndex
        x: line.width * 0.72 + 4
        width: line.width * 0.28 - 40
        height: parent.height
        elide: Text.ElideRight
        text: line.usable ? line.label : line.note
        color: Theme.dim
        TruncTip {}
    }
    AppText {
        objectName: "addLeave" + line.rowIndex
        visible: hover.hovered && line.add.rows.rowCount() > 1
        anchors.right: parent.right
        anchors.rightMargin: 14
        height: parent.height
        text: "✕"
        font.family: Theme.symbolFamily
        color: leaveHover.hovered ? Theme.bright : Theme.dim
        HoverHandler { id: leaveHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: line.add.leaveOut(line.rowIndex) }
    }
}
