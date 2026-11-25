pragma ComponentBehavior: Bound
import QtQuick

// A context / `•••` menu (mock showMenu): items {text, kind: "" | "check" | "off" | "divider", id}. The strings of the mock
// ("✓x" current, "~x" disabled, "-" divider) are accepted too. The current item gets the bright bar at its left
// (9.12, no tick). picked(index, id) fires for an enabled item.
Floating {
    id: menu

    property var items: []
    property int hot: -1
    signal picked(int index, string id)

    cardWidth: 190

    function parse(e) {
        if (typeof e !== "string")
            return e
        if (e === "-")
            return { kind: "divider", text: "" }
        if (e.charAt(0) === "✓")
            return { kind: "check", text: e.substring(1) }
        if (e.charAt(0) === "~")
            return { kind: "off", text: e.substring(1) }
        return { kind: "", text: e }
    }
    function pick(i) {
        if (!visible)
            return
        var it = parse(items[i])
        if (it.kind === "off" || it.kind === "divider")
            return
        close()
        picked(i, it.id || it.text)
    }
    function step(d) {
        var n = items.length
        for (var k = 1; k <= n; ++k) {
            var j = (hot + d * k + n * 2) % n
            var kind = parse(items[j]).kind
            if (kind !== "off" && kind !== "divider") {
                hot = j
                return
            }
        }
    }
    onVisibleChanged: if (visible) hot = -1

    Column {
        width: parent.width
        Repeater {
            model: menu.items
            delegate: Item {
                id: row
                required property int index
                required property var modelData
                readonly property var it: menu.parse(modelData)
                readonly property bool divider: it.kind === "divider"
                readonly property bool off: it.kind === "off"
                width: parent.width
                height: divider ? 9 : 30

                Rectangle {
                    visible: row.divider
                    x: 2
                    y: 4
                    width: parent.width - 4
                    height: 1
                    color: Theme.divider
                }
                Rectangle {
                    visible: !row.divider && !row.off && (rowHover.hovered || menu.hot === row.index)
                    anchors.fill: parent
                    radius: Theme.rRow
                    color: menu.onCard ? Theme.hotOnPanel : Theme.lift2
                }
                Rectangle {
                    visible: row.it.kind === "check"
                    x: 3
                    y: 7
                    width: 2
                    height: parent.height - 14
                    radius: 1
                    color: Theme.bright
                }
                AppText {
                    visible: !row.divider
                    objectName: "menuItem" + row.index
                    x: 10
                    height: parent.height
                    text: row.it.text
                    color: row.off ? Theme.faint : (row.it.kind === "check" || rowHover.hovered || menu.hot === row.index ? Theme.bright : Theme.text)
                }
                HoverHandler { id: rowHover; enabled: !row.divider && !row.off; cursorShape: Qt.PointingHandCursor }
                TipArea { enabled: !row.divider; tip: row.it.tip || "" }
                TapHandler { enabled: !row.divider && !row.off; onTapped: menu.pick(row.index) }
            }
        }
    }
    Keys.onDownPressed: step(1)
    Keys.onUpPressed: step(-1)
    Keys.onReturnPressed: if (hot >= 0) pick(hot)
}
