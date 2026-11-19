pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A chapter row of Translate (7.16): the title, a state word that takes the room it needs, the thin bar. The current chapter of a
// job is the lifted row; a chapter past a blocked one is faint. The word of a row with terms or problems is a link.
RowBase {
    id: row

    property var translate: null
    property bool picked: false
    required property string no
    required property string title
    required property real fraction
    required property real failed
    required property string word
    required property string tone
    required property var model
    readonly property var flagList: String(model.flags).split(",")
    readonly property bool beyond: flagList.indexOf("beyond") >= 0
    readonly property bool translated: flagList.indexOf("translated") >= 0
    readonly property bool live: flagList.indexOf("live") >= 0
    readonly property bool link: flagList.indexOf("terms") >= 0 || flagList.indexOf("problems") >= 0
    readonly property color wordColor: {
        if (tone === "red")
            return Theme.accent
        if (tone === "bright")
            return Theme.bright
        return link && wordHover.hovered ? Theme.bright : Theme.dim
    }

    leftPad: 8
    selected: picked
    current: model.current === true

    Item {
        id: cell
        width: row.width - 12 - row.leftPad
        height: Theme.rowHeight

        AppText {
            objectName: "trTitle" + row.rowIndex
            width: Math.max(40, parent.width - 110 - 16 - (wordText.visible ? wordText.implicitWidth + 12 : 0))
            height: parent.height
            elide: Text.ElideRight
            text: row.title
            color: row.beyond ? Theme.faint : (row.current || row.picked ? Theme.bright : Theme.text)
        }
        AppText {
            id: wordText
            objectName: "trWord" + row.rowIndex
            visible: row.word !== ""
            anchors.right: track.left
            anchors.rightMargin: 12
            height: parent.height
            text: row.word
            color: row.wordColor
            HoverHandler { id: wordHover; enabled: row.link; cursorShape: Qt.PointingHandCursor }
            TapHandler { enabled: row.link; onTapped: row.translate.wordClicked(row.rowIndex) }
            TipArea { tip: row.word !== "" ? row.translate.wordTip(row.rowIndex) : "" }
        }
        Rectangle {
            id: track
            objectName: "trBar" + row.rowIndex
            anchors.right: parent.right
            anchors.rightMargin: 8
            y: 12
            width: 110
            height: 5
            radius: 1
            color: Theme.s4
            opacity: row.fraction > 0 ? 1 : 0.5
            Rectangle {
                id: fill
                objectName: "trBarFill" + row.rowIndex
                width: parent.width * Math.min(1, row.fraction)
                height: parent.height
                radius: 1
                color: Theme.text
                Behavior on width {
                    enabled: row.live
                    NumberAnimation { duration: 400; easing.type: Easing.OutCubic }
                }
            }
            Rectangle {
                x: fill.width
                width: parent.width * Math.min(1 - Math.min(1, row.fraction), row.failed)
                height: parent.height
                radius: 1
                color: Theme.dim
            }
        }
    }
}
