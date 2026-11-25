pragma ComponentBehavior: Bound
import QtQuick

// Base of drop-downs and menus: fills the area it is placed in (usually the window root), catches a click outside
// (it closes and is not passed on, 9.7), closes on Esc, and places a lifted card under an anchor item or at a point.
FocusScope {
    id: floating

    property Item anchorItem: null
    property real cardWidth: 260
    property real maxCardHeight: 360
    property alias card: cardSurface
    default property alias content: inner.data
    property real contentHeight: inner.childrenRect.height
    readonly property bool onCard: Theme.onPanel(floating)       // opened over a panel card
    property real cardX: 0
    property real cardY: 0
    signal closed()

    anchors.fill: parent
    visible: false
    z: 500

    function rememberFocus() {
        keeper.remember()
    }
    function place(px, py) {
        cardX = Math.max(8, Math.min(px, width - cardWidth - 8))
        var h = cardSurface.height
        cardY = py + h > height - 8 ? Math.max(8, py - h - (anchorItem ? anchorItem.height + 8 : 0)) : py
    }
    function openUnder(item) {
        anchorItem = item
        var p = item.mapToItem(floating, 0, item.height + 4)
        rememberFocus()
        visible = true
        place(p.x, p.y)
        forceActiveFocus()
    }
    function openAt(px, py) {
        anchorItem = null
        rememberFocus()
        visible = true
        place(px, py)
        forceActiveFocus()
    }
    function close() {
        if (!visible)
            return
        visible = false
        closed()
    }

    onVisibleChanged: if (!visible) keeper.restore()
    FocusKeeper {
        id: keeper
        owner: floating
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onReleased: floating.close()            // not on the press: a hidden catcher would hand the release to the opener under it
    }
    Surface {
        id: cardSurface
        objectName: floating.objectName + "Card"
        x: floating.cardX
        y: floating.cardY
        width: floating.cardWidth
        height: Math.min(floating.maxCardHeight, floating.contentHeight + 10)
        level: 2
        radius: Theme.rMenu
        color: floating.onCard ? Theme.menuOnPanel : Theme.menu
        opacity: floating.visible ? 1 : 0
        transform: Translate { y: floating.visible ? 0 : -4 }
        Behavior on opacity { NumberAnimation { duration: Theme.durPop } }

        MouseArea { anchors.fill: parent }          // a click inside is not an outside click
        Item {
            id: inner
            x: 5
            y: 5
            width: parent.width - 10
            height: parent.height - 10
            clip: true
        }
    }
    Keys.onEscapePressed: close()
}
