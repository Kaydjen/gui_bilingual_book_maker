pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The tabs on top of the pane (7.16): Chapters | Problems N | Queue N | Sample. The chosen one is the pane's own colour and
// grows into it. The count of Problems / Queue follows the name, dim (red on Problems when a block failed).
Item {
    id: tabs

    property var translate: null
    readonly property var list: translate.tabs

    implicitWidth: row.width
    implicitHeight: 28

    Row {
        id: row
        spacing: 2
        Repeater {
            model: tabs.list
            delegate: Item {
                id: tab
                required property int index
                required property var modelData
                readonly property bool on: tab.modelData.id === tabs.translate.tab
                readonly property bool counted: tab.modelData.id === "problems" || tab.modelData.id === "queue"
                readonly property int cut: tab.modelData.text.lastIndexOf(" ")
                readonly property string label: counted && cut > 0 ? tab.modelData.text.substring(0, cut) : tab.modelData.text
                readonly property string count: counted && cut > 0 ? tab.modelData.text.substring(cut + 1) : ""
                width: caption.implicitWidth + (count !== "" ? countText.implicitWidth + 5 : 0) + 28
                height: tabs.height

                Rectangle {
                    visible: tab.on
                    anchors.fill: parent
                    topLeftRadius: 8
                    topRightRadius: 8
                    color: Theme.pane
                    Rectangle {
                        x: 8
                        width: parent.width - 16
                        height: 1
                        color: Theme.hairline
                    }
                }
                AppText {
                    id: caption
                    objectName: "trTab_" + tab.modelData.id
                    x: 14
                    height: parent.height
                    text: tab.label
                    color: tab.on || tabHover.hovered ? Theme.bright : Theme.dim
                }
                AppText {
                    id: countText
                    objectName: "trTabCount_" + tab.modelData.id
                    visible: tab.count !== ""
                    x: caption.x + caption.implicitWidth + 5
                    height: parent.height
                    text: tab.count
                    color: tab.modelData.tone === "red" ? Theme.accent : Theme.faint
                }
                HoverHandler { id: tabHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: tabs.translate.setTab(tab.modelData.id) }
                TipArea { tip: tab.modelData.tip || "" }
            }
        }
    }
}
