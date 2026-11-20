pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Time popover (7.16): the paragraphs per request as three radio rows with their times (10 is `untested`), then the API keys
// row (click = Settings at the keys), the requests left today with the meter and the time they renew. While the series
// runs the choice is locked (greyed, the tooltip says so).
Floating {
    id: pop

    property var translate: null
    readonly property var info: translate.time.pop || ({})
    readonly property bool locked: info.locked === true
    readonly property string renewText: info.renew || ""
    readonly property int split: renewText.lastIndexOf(" ")

    cardWidth: 390

    function openRight(item) {
        anchorItem = item
        var p = item.mapToItem(pop, item.width, item.height + 4)
        visible = true
        place(p.x - cardWidth, p.y)
        forceActiveFocus()
    }

    Column {
        width: parent.width
        topPadding: 5
        bottomPadding: 3
        AppText {
            objectName: "timeHeading"
            x: 9
            height: 26
            text: pop.info.heading || ""
            color: Theme.dim
        }
        Repeater {
            model: pop.info.options || []
            delegate: Item {
                id: opt
                required property int index
                required property var modelData
                width: parent.width
                height: 30

                Rectangle {
                    visible: !pop.locked && optHover.hovered
                    anchors.fill: parent
                    radius: Theme.rRow
                    color: Theme.lift2
                }
                Rectangle {
                    objectName: "timeRing" + opt.index
                    x: 9
                    anchors.verticalCenter: parent.verticalCenter
                    width: 12
                    height: 12
                    radius: 6
                    color: "transparent"
                    border.width: opt.modelData.selected ? 4 : 1
                    border.color: opt.modelData.selected ? (pop.locked ? Theme.dim : Theme.bright) : Theme.dim
                }
                AppText {
                    id: optLabel
                    objectName: "timeOption" + opt.index
                    x: 31
                    height: parent.height
                    text: opt.modelData.text
                    color: pop.locked ? Theme.faint : (opt.modelData.selected || optHover.hovered ? Theme.bright : Theme.text)
                }
                AppText {
                    objectName: "timeUntested" + opt.index
                    visible: opt.modelData.untested === true
                    x: optLabel.x + optLabel.implicitWidth + 8
                    height: parent.height
                    text: "untested"
                    color: Theme.faint
                }
                AppText {
                    objectName: "timeValue" + opt.index
                    anchors.right: parent.right
                    anchors.rightMargin: 9
                    height: parent.height
                    text: opt.modelData.time
                    color: pop.locked ? Theme.faint : Theme.text
                }
                HoverHandler { id: optHover; cursorShape: pop.locked ? Qt.ArrowCursor : Qt.PointingHandCursor }
                TapHandler {
                    enabled: !pop.locked
                    onTapped: {
                        pop.translate.setPerRequest(opt.modelData.per)
                        pop.close()
                    }
                }
                TipArea { tip: (pop.locked ? (pop.info.lockTip || "") + "\n" : "") + (opt.modelData.tip || "") }
            }
        }
        Rectangle {
            x: 2
            width: parent.width - 4
            height: 9
            color: "transparent"
            Rectangle {
                y: 4
                width: parent.width
                height: 1
                color: Theme.divider
            }
        }
        Item {
            id: keys
            objectName: "timeKeys"
            width: parent.width
            height: 28
            Rectangle {
                visible: keysHover.hovered
                anchors.fill: parent
                radius: Theme.rRow
                color: Theme.lift2
            }
            AppText {
                x: 9
                height: parent.height
                text: pop.info.keysText ? pop.info.keysText.replace(" ›", "") : ""
                color: keysHover.hovered ? Theme.bright : Theme.dim
            }
            AppText {
                anchors.right: parent.right
                anchors.rightMargin: 9
                height: parent.height
                text: "›"
                color: keysHover.hovered ? Theme.bright : Theme.dim
            }
            HoverHandler { id: keysHover; cursorShape: Qt.PointingHandCursor }
            TapHandler {
                onTapped: {
                    pop.close()
                    pop.translate.openKeys()
                }
            }
            TipArea { tip: pop.info.keysTip || "" }
        }
        Item {
            width: parent.width
            height: 28
            AppText {
                x: 9
                height: parent.height
                text: pop.info.leftLabel || ""
                color: Theme.dim
                TipArea { tip: pop.info.leftTip || "" }
            }
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 9
                height: parent.height
                spacing: 5
                AppText {
                    objectName: "timeLeft"
                    height: parent.height
                    text: (pop.info.leftText || "").split(" / ")[0]
                    color: Theme.text
                }
                AppText {
                    height: parent.height
                    text: "/ " + ((pop.info.leftText || "").split(" / ")[1] || "")
                    color: Theme.faint
                }
            }
        }
        Item {
            width: parent.width
            height: 9
            Rectangle {
                objectName: "timeMeter"
                x: 9
                y: 1
                width: parent.width - 18
                height: 3
                radius: 1.5
                color: Theme.s3
                Rectangle {
                    width: parent.width * Math.max(0, Math.min(1, pop.info.meter || 0))
                    height: parent.height
                    radius: 1.5
                    color: Theme.dim
                }
            }
        }
        Item {
            visible: pop.renewText !== ""
            width: parent.width
            height: 28
            AppText {
                x: 9
                height: parent.height
                text: pop.renewText.substring(0, pop.split)
                color: Theme.dim
            }
            AppText {
                objectName: "timeRenew"
                anchors.right: parent.right
                anchors.rightMargin: 9
                height: parent.height
                text: pop.renewText.substring(pop.split + 1)
                color: Theme.text
            }
        }
    }
}
