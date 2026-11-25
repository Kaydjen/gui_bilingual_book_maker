pragma ComponentBehavior: Bound
import QtQuick
import Novel
import Books

// A row of the Export map (8.7): the `▸` of a piece, its box, the range (two framed fields while the piece is open), ONE mark
// right after it. A piece row, a chapter row of an opened piece, a gap row (faint, no box, `Translate ›`) and the job's
// `Translating` row. A click anywhere on a row toggles it like its box; the `▸` and the marks are links with their own meaning.
RowBase {
    id: row

    property var exp: null
    property bool narrow: false
    required property string kind
    required property string label
    required property string title
    required property string mark
    required property string markKind
    required property string box
    required property string flags
    required property string span
    required property var model
    readonly property var flagList: flags.split(",")
    readonly property bool sel: flagList.indexOf("sel") >= 0
    readonly property bool old: flagList.indexOf("old") >= 0
    readonly property bool faint: flagList.indexOf("faint") >= 0
    readonly property bool hatch: flagList.indexOf("hatch") >= 0
    readonly property bool isOpen: flagList.indexOf("open") >= 0
    readonly property bool isChapter: kind === "chapter"
    readonly property bool isPiece: kind === "piece"
    readonly property color rangeColor: sel ? Theme.bright : (faint ? Theme.faint : (old ? Theme.dim : Theme.text))

    function parts() {
        var p = span.split("|")
        return p.length === 2 ? p : ["", ""]
    }
    function refill() {
        var p = parts()
        fromField.value = p[0]
        toField.value = p[1]
        fromField.input.text = p[0]
        toField.input.text = p[1]
    }
    function digits(t) {
        return /^\s*\d+\s*$/.test(t)
    }
    function spanCommitted() {
        if (!exp.setSpan(rowIndex, fromField.value, toField.value)) {
            fromField.flash()
            toField.flash()
            refill()
        }
    }

    leftPad: 8
    height: isChapter ? 26 : Theme.rowHeight
    selected: sel
    current: Focus.byKey && row.rowIndex === exp.cursor
    onSpanChanged: refill()
    Component.onCompleted: refill()

    Image {
        objectName: "exHatch" + row.rowIndex
        parent: row
        visible: row.hatch
        x: 6
        width: parent.width - 12
        height: parent.height
        z: -0.5
        source: Theme.assetsBase + "hatch.png"
        fillMode: Image.Tile
    }

    // the `▸` / `▾` of a piece
    Item {
        width: 20
        height: row.height
        AppText {
            objectName: "exTw" + row.rowIndex
            visible: row.isPiece
            anchors.centerIn: parent
            text: row.isOpen ? "▾" : "▸"
            font.pixelSize: Theme.fontSmall
            font.family: Theme.symbolFamily
            color: twMouse.containsMouse ? Theme.bright : Theme.dim
        }
        MouseArea {
            id: twMouse
            visible: row.isPiece
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.exp.toggleOpen(row.rowIndex)
            TipArea { tip: row.exp.tips.open }
        }
    }
    // the box
    Item {
        width: 28
        height: row.height
        CheckMark {
            objectName: "exBox" + row.rowIndex
            visible: row.box !== "none"
            anchors.centerIn: parent
            checked: row.box === "on"
            dash: row.box === "part"
            hot: row.hovered
        }
    }
    // the range: a label, or the two fields of an opened piece
    Item {
        id: rangeCell
        width: row.narrow ? 170 : 210
        height: row.height
        AppText {
            objectName: "exRange" + row.rowIndex
            visible: !row.isOpen
            x: row.isChapter ? 22 : 0
            height: parent.height
            text: row.label
            color: row.rangeColor
        }
        Row {
            visible: row.isOpen
            height: parent.height
            spacing: 6
            Field {
                id: fromField
                objectName: "exFrom" + row.rowIndex
                anchors.verticalCenter: parent.verticalCenter
                width: 62
                height: 24
                validate: t => row.digits(t)
                onCommitted: row.spanCommitted()
                onRejected: row.refill()
                TipArea { tip: row.exp.tips.from }
            }
            AppText {
                height: parent.height
                text: "–"
                color: Theme.dim
            }
            Field {
                id: toField
                objectName: "exTo" + row.rowIndex
                anchors.verticalCenter: parent.verticalCenter
                width: 62
                height: 24
                validate: t => row.digits(t)
                onCommitted: row.spanCommitted()
                onRejected: row.refill()
                TipArea { tip: row.exp.tips.to }
            }
        }
    }
    // the title of a chapter row of an opened piece (a failed chapter shows its red mark instead)
    AppText {
        id: titleText
        visible: row.isChapter
        objectName: "exTitle" + row.rowIndex
        width: Math.max(40, row.width - 12 - row.leftPad - 20 - 28 - rangeCell.width - 16)
        height: row.height
        elide: Text.ElideRight
        text: row.markKind === "problem" ? row.mark : row.title
        color: row.markKind === "problem" ? row.markColor() : Theme.dim
        MouseArea {
            enabled: row.markKind === "problem"
            x: 0
            width: titleText.contentWidth
            height: parent.height
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.exp.markClicked(row.rowIndex)
            TipArea { tip: row.markKind === "problem" ? row.exp.tips.problemChapter : "" }
        }
    }
    // the mark of a piece, a gap or the job's row
    Item {
        id: markCell
        visible: !row.isChapter
        width: Math.max(0, row.width - 12 - row.leftPad - 20 - 28 - rangeCell.width - 8)
        height: row.height
        Rectangle {
            visible: row.markKind === "go" && markMouse.containsMouse
            x: -8
            anchors.verticalCenter: parent.verticalCenter
            width: markText.implicitWidth + 16 - 0
            height: 24
            radius: 5
            color: Theme.s3
        }
        AppText {
            id: markText
            objectName: "exMark" + row.rowIndex
            visible: row.mark !== ""
            height: parent.height
            text: row.mark
            color: row.markColor()
        }
        MouseArea {
            id: markMouse
            visible: row.mark !== "" && row.markKind !== "part" && row.markKind !== "wave"
            x: row.markKind === "go" ? -8 : 0
            width: markText.implicitWidth + (row.markKind === "go" ? 16 : 0)
            height: parent.height
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.exp.markClicked(row.rowIndex)
        }
        TipArea {
            tip: row.exp.rev >= 0 && row.mark !== "" ? row.exp.markTip(row.rowIndex) : ""
        }
    }
    function markColor() {
        if (markKind === "problem")
            return Theme.accent
        if (markKind === "part")
            return Theme.bright
        if (markKind === "go")
            return markMouse.containsMouse ? Theme.bright : Theme.text
        if (markKind === "exported")
            return markMouse.containsMouse ? Theme.bright : Theme.dim
        return Theme.dim
    }
}
