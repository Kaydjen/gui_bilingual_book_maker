pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Sample tab (7.16): the title (`Sample · 7 terms unreviewed`, no red) with the chapter it was taken from, then the pairs:
// the source dim on the left, the translation on the right; an answer still to come is a quiet placeholder.
Item {
    id: tab

    property var translate: null
    readonly property var info: translate.sampleResult
    readonly property bool pending: info.pending === true
    property real glint: 0
    readonly property var shownRows: (tab.info.rows || []).length === 0 && tab.pending
                                     ? [{ src: "", tr: "", failed: false }, { src: "", tr: "", failed: false }, { src: "", tr: "", failed: false }]
                                     : (tab.info.rows || [])

    // the list keeps its place when rows are added at the end (`Next 50`): only rows that are new are appended
    function sameStart(rows) {
        if (rowsList.count > rows.length)
            return false
        for (var i = 0; i < rowsList.count; ++i)
            if (rowsList.get(i).src !== (rows[i].src || ""))
                return false
        return true
    }
    function row(r) {
        return { src: r.src || "", tr: r.tr || "", failed: r.failed === true }
    }
    function sync() {
        var rows = tab.shownRows
        if (!sameStart(rows))
            rowsList.clear()
        for (var i = 0; i < rows.length; ++i) {
            if (i < rowsList.count)
                rowsList.set(i, row(rows[i]))
            else
                rowsList.append(row(rows[i]))
        }
    }
    onShownRowsChanged: sync()
    Component.onCompleted: sync()

    ListModel {
        id: rowsList
    }

    Item {
        id: head
        objectName: "sampleHead"
        width: parent.width
        height: 34
        Row {
            x: 12
            height: parent.height
            spacing: 10
            AppText {
                objectName: "sampleTitle"
                height: parent.height
                text: tab.info.title || "Sample"
                color: Theme.bright
                TipArea { tip: tab.info.unreviewedTip || "" }
            }
            AppText {
                objectName: "sampleSub"
                height: parent.height
                text: tab.info.sub || ""
                color: Theme.dim
            }
        }
        Pill {
            objectName: "sampleNext"
            visible: tab.info.more === true
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            height: 26
            kind: tab.info.nextEnabled === true ? "flat" : "off"
            text: "Next 50"
            tip: tab.info.nextTip || ""
            onClicked: tab.translate.sampleNext()
        }
        Rectangle {
            anchors.bottom: parent.bottom
            x: 6
            width: parent.width - 12
            height: 1
            color: Theme.rowLine
        }
    }
    ListView {
        id: view
        objectName: "sampleList"
        y: head.height
        width: parent.width
        height: parent.height - head.height
        bottomMargin: 84
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: rowsList
        delegate: Item {
            id: pair
            required property int index
            required property string src
            required property string tr
            required property bool failed
            readonly property bool blank: pair.src === ""
            readonly property bool waiting: tab.pending && pair.tr === "" && !pair.failed
            width: ListView.view.width
            height: Math.max(blank ? 28 : source.height, waiting ? 28 : target.height) + 20

            Rectangle {
                anchors.bottom: parent.bottom
                x: 6
                width: parent.width - 12
                height: 1
                color: Theme.rowLine
            }
            Rectangle {
                x: parent.width / 2
                width: 1
                height: parent.height
                color: Theme.divider
            }
            ReadText {
                id: source
                objectName: "sampleSource" + pair.index
                visible: !pair.blank
                x: 14
                y: 10
                width: parent.width / 2 - 28
                plain: pair.src
                color: Theme.dim
            }
            ReadText {
                id: target
                objectName: "sampleTarget" + pair.index
                visible: !pair.waiting
                x: parent.width / 2 + 14
                y: 10
                width: parent.width / 2 - 28
                plain: pair.failed ? "not translated" : pair.tr
                color: pair.failed ? Theme.dim : Theme.bright
            }
            SkeletonBars {
                objectName: "sampleSkeleton" + pair.index
                visible: pair.waiting
                x: parent.width / 2 + 14
                y: 14
                width: pair.width / 2 - 28
                glint: tab.glint
            }
            SkeletonBars {
                objectName: "sampleSourceSkeleton" + pair.index
                visible: pair.blank
                x: 14
                y: 14
                width: pair.width / 2 - 28
                glint: tab.glint
            }
        }
    }
    ScrollAssist {
        flickable: view
    }
    Fades {
        flickable: view
        topOffset: head.height
    }
    SequentialAnimation {
        running: Visual.live && tab.visible && tab.pending
        loops: Animation.Infinite
        NumberAnimation { target: tab; property: "glint"; from: 0; to: 1; duration: 650 }
        NumberAnimation { target: tab; property: "glint"; from: 1; to: 0; duration: 650 }
    }
}
