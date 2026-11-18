pragma ComponentBehavior: Bound
import QtQuick

// A segmented switch / tabs (mock .seg, .tabs): inset well, the chosen segment is a small lifted pill.
Item {
    id: seg

    property var model: []                 // strings or {text, id, tip}
    property int currentIndex: 0
    property bool off: false
    signal activated(int index)

    implicitWidth: row.implicitWidth + 6
    implicitHeight: 32

    Inset {
        anchors.fill: parent
        color: Theme.pane
        radius: 8
        edge: "transparent"
    }
    Row {
        id: row
        x: 3
        y: 3
        spacing: 0
        Repeater {
            model: seg.model
            delegate: Item {
                id: cell
                required property int index
                required property var modelData
                readonly property string label: typeof modelData === "string" ? modelData : modelData.text
                readonly property bool on: index === seg.currentIndex
                width: txt.implicitWidth + 24
                height: 26

                Surface {
                    anchors.fill: parent
                    visible: cell.on
                    level: seg.off ? 0 : 1
                    radius: Theme.rRow
                    color: seg.off ? Theme.pillOff : Theme.lift
                }
                AppText {
                    id: txt
                    objectName: "segText" + cell.index
                    anchors.centerIn: parent
                    text: cell.label
                    color: seg.off ? (cell.on ? Theme.dim : Theme.faint) : (cell.on || cellHover.hovered ? Theme.bright : Theme.dim)
                }
                HoverHandler { id: cellHover; cursorShape: seg.off ? Qt.ArrowCursor : Qt.PointingHandCursor }
                TapHandler { enabled: !seg.off; onTapped: seg.activated(cell.index) }
                TipArea { tip: typeof cell.modelData === "string" ? "" : (cell.modelData.tip || "") }
            }
        }
    }
}
