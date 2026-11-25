pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A row of the Queue tab (7.16 F7): the start column (now / ≈ 14:20 / next / then / 09:01), the name bright and its detail
// dim, the running job's bar + percent + a flat Stop, in a quota wait `Resumes 09:01` + a flat Don't resume, and at the right
// edge, on hover only, ↑ ↓ and ✕ apart. A click on the name opens that series on Translate.
Item {
    id: row

    property var translate: null
    required property int index
    required property string start
    required property string name
    required property string detail
    required property int percent
    required property string flags
    required property string why
    required property string tip
    readonly property var flagList: flags.split(",")
    readonly property bool running: flagList.indexOf("running") >= 0
    readonly property bool wait: flagList.indexOf("wait") >= 0
    readonly property bool stuck: flagList.indexOf("stuck") >= 0
    readonly property bool canUp: flagList.indexOf("up") >= 0
    readonly property bool canDown: flagList.indexOf("down") >= 0
    readonly property bool hovered: hover.hovered
    readonly property bool bright: start === "now" || wait

    width: ListView.view ? ListView.view.width : 400
    height: 40

    Rectangle {
        x: 6
        width: parent.width - 12
        height: parent.height
        radius: Theme.rRow
        color: Theme.rowHover
        visible: row.hovered
    }
    AppText {
        objectName: "queueStart" + row.index
        x: 6 + 22
        width: 70
        height: parent.height
        text: row.start
        color: row.bright ? Theme.bright : Theme.dim
    }
    Row {
        id: nameRow
        x: 6 + 22 + 70
        height: parent.height
        width: Math.max(60, parent.width - x - cluster.width - 20)
        clip: true
        AppText {
            id: nameText
            objectName: "queueName" + row.index
            height: parent.height
            text: row.name
            color: Theme.bright
            font.underline: nameHover.hovered
            HoverHandler { id: nameHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: row.translate.queueOpen(row.index) }
        }
        AppText {
            objectName: "queueDetail" + row.index
            height: parent.height
            leftPadding: 8
            text: row.detail
            color: Theme.dim
        }
    }
    TipArea {
        anchors.fill: undefined
        x: nameRow.x
        width: nameRow.width
        height: parent.height
        tip: row.tip
    }
    Row {
        id: cluster
        anchors.right: parent.right
        anchors.rightMargin: 16
        height: parent.height
        spacing: 0

        Rectangle {
            objectName: "queueBar" + row.index
            visible: row.running && !row.wait
            anchors.verticalCenter: parent.verticalCenter
            width: 120
            height: 5
            radius: 1
            color: Theme.s4
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, row.percent / 100))
                height: parent.height
                radius: 1
                color: Theme.text
            }
        }
        AppText {
            objectName: "queuePercent" + row.index
            visible: row.running && !row.wait
            width: 48
            height: parent.height
            horizontalAlignment: Text.AlignRight
            text: row.percent + " %"
            color: Theme.text
        }
        AppText {
            objectName: "queueWait" + row.index
            visible: row.wait
            height: parent.height
            rightPadding: 14
            text: "Resumes " + row.start
            color: Theme.dim
        }
        AppText {
            objectName: "queueWhy" + row.index
            visible: row.stuck
            height: parent.height
            rightPadding: 14
            text: row.why
            color: whyHover.hovered ? Theme.accentHover : Theme.accent
            font.underline: whyHover.hovered
            HoverHandler { id: whyHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: row.translate.queueOpen(row.index) }
            TipArea { tip: row.tip }
        }
        Pill {
            objectName: "queueStop" + row.index
            visible: row.running && !row.wait
            anchors.verticalCenter: parent.verticalCenter
            kind: "flat"
            text: "Stop"
            tip: row.translate.tips.queueStop
            onClicked: row.translate.queueStop()
        }
        Pill {
            objectName: "queueDontResume" + row.index
            visible: row.wait
            anchors.verticalCenter: parent.verticalCenter
            kind: "flat"
            text: "Don't resume"
            tip: row.translate.tips.dontResume
            onClicked: row.translate.queueDontResume()
        }
        Item {
            id: moves
            objectName: "queueMoves" + row.index
            visible: !row.running
            opacity: row.hovered ? 1 : 0
            width: 56
            height: parent.height
            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Repeater {
                    model: [{ text: "↑", on: row.canUp, tip: row.translate.tips.queueUp, up: true },
                            { text: "↓", on: row.canDown, tip: row.translate.tips.queueDown, up: false }]
                    delegate: Item {
                        id: arrow
                        required property var modelData
                        width: 24
                        height: 24
                        visible: arrow.modelData.on
                        Rectangle {
                            anchors.fill: parent
                            radius: 4
                            color: Theme.lift2
                            visible: arrowHover.hovered
                        }
                        AppText {
                            anchors.centerIn: parent
                            font.family: Theme.symbolFamily
                            text: arrow.modelData.text
                            color: arrowHover.hovered ? Theme.bright : Theme.dim
                        }
                        HoverHandler { id: arrowHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: arrow.modelData.up ? row.translate.queueUp(row.index) : row.translate.queueDown(row.index)
                        }
                        TipArea { tip: arrow.modelData.tip }
                    }
                }
            }
        }
        Item {
            objectName: "queueRemove" + row.index
            visible: !row.running
            opacity: row.hovered ? 1 : 0
            width: 28
            height: parent.height
            AppText {
                anchors.centerIn: parent
                font.family: Theme.symbolFamily
                text: "✕"
                color: removeHover.hovered ? Theme.bright : Theme.dim
            }
            HoverHandler { id: removeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: row.translate.queueRemove(row.index) }
            TipArea { tip: row.translate.tips.queueRemove }
        }
    }
    HoverHandler { id: hover }
}
