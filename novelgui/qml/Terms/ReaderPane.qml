pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The reader under the table (6.7, 6.6): only while one term is selected. The term is underlined in its paragraph, `‹ 3 / 314 ›`
// (Alt+Left / Alt+Right) steps through the places; the places are found in batches off the UI thread, so the counter grows while
// the search runs. A splitter above the pane resizes it.
Item {
    id: pane

    property var terms: null
    readonly property var info: terms.reader
    property real wanted: 200

    implicitHeight: wanted + 10

    Item {
        id: split
        objectName: "readerSplit"
        width: parent.width
        height: 10
        HoverHandler { cursorShape: Qt.SizeVerCursor }
        Rectangle {
            anchors.centerIn: parent
            width: 40
            height: 2
            radius: 1
            color: Theme.s4
        }
        DragHandler {
            target: null
            xAxis.enabled: false
            property real base: 0
            onActiveChanged: if (active) base = pane.wanted
            onTranslationChanged: if (active) pane.wanted = Math.max(110, Math.min(pane.parent.height - 140, base - translation.y))
        }
    }
    Rectangle {
        y: 10
        width: parent.width
        height: parent.height - 10
        radius: Theme.rPane
        color: Theme.s1

        Item {
            id: head
            width: parent.width
            height: 32
            Row {
                x: 12
                height: parent.height
                spacing: 10
                AppText {
                    objectName: "readerTerm"
                    height: parent.height
                    text: pane.info.title || ""
                    color: Theme.bright
                }
                AppText {
                    objectName: "readerChapter"
                    height: parent.height
                    text: pane.info.chapter || ""
                    color: Theme.dim
                }
            }
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 12
                height: parent.height
                spacing: 10
                AppText {
                    objectName: "readerPrev"
                    height: parent.height
                    text: "‹"
                    font.family: Theme.symbolFamily
                    color: prevHover.hovered ? Theme.bright : Theme.dim
                    HoverHandler { id: prevHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: pane.terms.stepPlace(-1) }
                    TipArea { tip: pane.terms.tips.prev }
                }
                AppText {
                    objectName: "readerCounter"
                    height: parent.height
                    text: pane.info.total > 0 ? pane.info.place + " / " + pane.info.total : (pane.info.searching ? "…" : "0")
                    color: Theme.dim
                    TipArea { tip: pane.info.tip || "" }
                }
                AppText {
                    objectName: "readerNext"
                    height: parent.height
                    text: "›"
                    font.family: Theme.symbolFamily
                    color: nextHover.hovered ? Theme.bright : Theme.dim
                    HoverHandler { id: nextHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: pane.terms.stepPlace(1) }
                    TipArea { tip: pane.terms.tips.next }
                }
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.rowLine
            }
        }
        Flickable {
            id: body
            objectName: "readerBody"
            y: head.height + 10
            x: 16
            width: parent.width - 32
            height: parent.height - y - 6
            contentHeight: paragraphs.height
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: paragraphs
                width: body.width
                spacing: 8
                ReadText {
                    objectName: "readerBefore"
                    width: parent.width
                    leading: 1.4
                    rich: pane.info.before || ""
                    color: Theme.dim
                    visible: rich !== ""
                }
                ReadText {
                    objectName: "readerText"
                    width: parent.width
                    leading: 1.4
                    rich: pane.info.text || ""
                    color: Theme.text
                }
                ReadText {
                    objectName: "readerAfter"
                    width: parent.width
                    leading: 1.4
                    rich: pane.info.after || ""
                    color: Theme.dim
                    visible: rich !== ""
                }
            }
        }
        ScrollAssist {
            flickable: body
        }
    }
}
