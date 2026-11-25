pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Reader tab (14.2): a tab `Reader · 2703` with `✕`, the chapter title with the version chooser `r1 ▾`, and the block
// pairs: the source dim on the left, the translation on the right; a block with a flag or a problem carries a dim mark. Read-only
// until core C15 (hand edits): the translation cells do not edit and say why in a tooltip.
Item {
    id: tab

    property var reader: null

    Row {
        id: strip
        x: 16
        y: 16
        height: 30
        spacing: 6
        Surface {
            objectName: "readerTab"
            width: label.implicitWidth + 40
            height: parent.height
            level: 1
            radius: Theme.rControl
            color: Theme.lift
            AppText {
                id: label
                objectName: "readerTabText"
                x: 14
                height: parent.height
                text: tab.reader.tabText
                color: Theme.bright
            }
            AppText {
                objectName: "readerClose"
                anchors.right: parent.right
                anchors.rightMargin: 10
                height: parent.height
                text: "✕"
                font.family: Theme.symbolFamily
                color: closeHover.hovered ? Theme.bright : Theme.dim
                HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: tab.reader.close() }
                TipArea { tip: tab.reader.tips.close }
            }
        }
    }
    Rectangle {
        x: 16
        y: strip.y + strip.height + 10
        width: parent.width - 32
        height: parent.height - y - 16
        radius: Theme.rPane
        color: Theme.s1

        Item {
            id: bar
            width: parent.width
            height: 40
            AppText {
                objectName: "readerTitle"
                x: 16
                width: parent.width - 120
                height: parent.height
                elide: Text.ElideRight
                text: tab.reader.title
                color: Theme.bright
                font.weight: Font.DemiBold
            }
            Pill {
                objectName: "readerVersion"
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: tab.reader.version + " ▾"
                tip: tab.reader.tips.version
                onClicked: tab.openVersions(this)
            }
            Rectangle {
                anchors.bottom: parent.bottom
                x: 8
                width: parent.width - 16
                height: 1
                color: Theme.rowLine
            }
        }
        ListView {
            id: pairs
            objectName: "readerPairs"
            y: bar.height
            width: parent.width
            height: parent.height - bar.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            bottomMargin: 20
            model: tab.reader.blocks
            delegate: Item {
                id: pair
                required property string source
                required property string target
                required property string mark
                width: ListView.view.width
                height: Math.max(src.height, dst.height) + 14
                ReadText {
                    id: src
                    objectName: "readerSource"
                    x: 16
                    y: 7
                    width: parent.width / 2 - 24
                    leading: 1
                    plain: pair.source
                    color: Theme.dim
                }
                ReadText {
                    id: dst
                    objectName: "readerTarget"
                    x: parent.width / 2 + 8
                    y: 7
                    width: parent.width / 2 - 24 - (pair.mark !== "" ? 56 : 0)
                    leading: 1
                    plain: pair.target !== "" ? pair.target : "—"
                    color: pair.target !== "" ? Theme.text : Theme.faint
                    TipArea { tip: tab.reader.tips.edit }
                }
                AppText {
                    visible: pair.mark !== ""
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    y: 7
                    text: pair.mark
                    font.pixelSize: Theme.fontSmall
                    color: Theme.dim
                }
            }
        }
        ScrollAssist {
            flickable: pairs
        }
        Fades {
            flickable: pairs
            color: Theme.s1
            topOffset: bar.height
        }
        Spinner {
            visible: tab.reader.loading
            anchors.centerIn: parent
            active: visible
        }
        AppText {
            objectName: "readerError"
            visible: tab.reader.error !== ""
            anchors.centerIn: parent
            text: tab.reader.error
            color: Theme.dim
        }
    }
    property Item versionAnchor: null
    function openVersions(anchor) {
        versionAnchor = anchor
        if (versions.active)
            versions.item.openUnder(anchor)         // qmllint disable missing-property
        else
            versions.active = true
    }
    Loader {
        id: versions
        active: false
        anchors.fill: parent
        sourceComponent: DropDown {
            objectName: "readerVersions"
            cardWidth: 160
            entries: [{ text: tab.reader.version, current: true }]
        }
        onLoaded: item.openUnder(tab.versionAnchor)         // qmllint disable missing-property
    }
}
