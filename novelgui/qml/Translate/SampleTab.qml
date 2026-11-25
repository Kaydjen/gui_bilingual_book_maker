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
        model: (tab.info.rows || []).length === 0 && tab.pending ? [{ src: "", tr: "" }, { src: "", tr: "" }, { src: "", tr: "" }] : (tab.info.rows || [])
        delegate: Item {
            id: pair
            required property int index
            required property var modelData
            readonly property bool blank: (pair.modelData.src || "") === ""
            readonly property bool waiting: tab.pending && (pair.modelData.tr || "") === ""
            width: ListView.view.width
            height: Math.max(blank ? 28 : source.implicitHeight, waiting ? 28 : target.implicitHeight) + 20

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
            AppText {
                id: source
                objectName: "sampleSource" + pair.index
                visible: !pair.blank
                x: 14
                y: 10
                width: parent.width / 2 - 28
                height: implicitHeight
                verticalAlignment: Text.AlignTop
                wrapMode: Text.Wrap
                lineHeight: 1.3
                text: pair.modelData.src
                color: Theme.dim
            }
            AppText {
                id: target
                objectName: "sampleTarget" + pair.index
                visible: !pair.waiting
                x: parent.width / 2 + 14
                y: 10
                width: parent.width / 2 - 28
                height: implicitHeight
                verticalAlignment: Text.AlignTop
                wrapMode: Text.Wrap
                lineHeight: 1.3
                text: pair.modelData.failed ? "not translated" : (pair.modelData.tr || "")
                color: pair.modelData.failed ? Theme.dim : Theme.bright
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
