pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The three tabs of Terms (6.7): Blocking N, Not confirmed N, Confirmed N. The active one is a small lifted pill; Blocking is
// dim while nothing is selected in Books. Counts follow the type filter; `…` while the book is read.
// The tabs sit in an inset well (mock .tabs), as Segmented does.
Item {
    id: tabs

    property var terms: null

    implicitWidth: strip.implicitWidth + 6
    implicitHeight: 34

    Inset {
        anchors.fill: parent
        color: Theme.pane
        radius: 8
        edge: "transparent"
    }
    Row {
        id: strip
        x: 3
        y: 3
        spacing: 0
        Repeater {
            model: tabs.terms.tabList
            delegate: Item {
                id: tab
                required property var modelData
                width: inner.implicitWidth + 28
                height: 28

                Surface {
                    visible: tab.modelData.on
                    anchors.fill: parent
                    level: 1
                    radius: Theme.rControl
                    color: Theme.lift
                }
                Row {
                    id: inner
                    anchors.centerIn: parent
                    spacing: 8
                    AppText {
                        id: label
                        objectName: "tab_" + tab.modelData.id
                        text: tab.modelData.text
                        color: tab.modelData.dim ? Theme.faint : (tab.modelData.on || tabHover.hovered ? Theme.bright : Theme.dim)
                    }
                    AppText {
                        objectName: "tabCount_" + tab.modelData.id
                        text: tab.modelData.count
                        color: tab.modelData.dim ? Theme.faint : Theme.dim
                    }
                }
                HoverHandler { id: tabHover; cursorShape: tab.modelData.dim ? Qt.ArrowCursor : Qt.PointingHandCursor }
                TapHandler { onTapped: tabs.terms.selectTab(tab.modelData.id) }
                TipArea { tip: tab.modelData.tip }
            }
        }
    }
}
