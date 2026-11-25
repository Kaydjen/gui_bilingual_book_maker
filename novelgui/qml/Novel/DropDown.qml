pragma ComponentBehavior: Bound
import QtQuick

// A drop-down card (mock dd): optional typing filter, group headings, items; the current item is bright with a short bar
// at its left edge. entries: {group: "Heading"} | {text, id, note, current, off}. Typing fires filterChanged(text):
// the owner narrows `entries` (the hook), nothing is filtered here. Up / Down / Enter / Esc work from the keyboard;
// with typed text and nothing highlighted Enter takes the first match.
Floating {
    id: dd

    property var entries: []
    property bool filtering: false
    property string filterText: ""
    property string placeholder: ""
    property int hot: -1
    signal picked(int index, string id)
    signal filterChanged(string text)

    cardWidth: 260
    maxCardHeight: 320

    function selectable(e) {
        return e && e.group === undefined && !e.off
    }
    function step(d) {
        var n = entries.length
        for (var k = 1; k <= n; ++k) {
            var j = (hot + d * k + n * 2) % n
            if (selectable(entries[j])) {
                hot = j
                list.positionViewAtIndex(j, ListView.Contain)
                return
            }
        }
    }
    function enter() {
        if (hot < 0 && filterText !== "")
            step(1)                     // typed text: Enter takes the first match (a new name's `+` entry included)
        if (hot >= 0)
            pick(hot)
    }
    function pick(i) {
        if (!visible)
            return
        var e = entries[i]
        if (!selectable(e))
            return
        close()
        picked(i, e.id !== undefined ? e.id : e.text)
    }
    onVisibleChanged: {
        if (visible) {
            hot = -1
            filterText = ""
            filterField.text = ""
            if (filtering)
                filterField.forceActiveFocus()
        }
    }

    Column {
        width: parent.width
        spacing: 4

        Inset {
            visible: dd.filtering
            width: parent.width
            height: 28
            edge: filterField.activeFocus ? Theme.fieldFocus : Theme.s3
            AppText {
                visible: filterField.text === ""
                x: 8
                height: parent.height
                text: dd.placeholder
                color: Theme.faint
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.IBeamCursor
                onPressed: filterField.forceActiveFocus()
            }
            TextInput {
                id: filterField
                objectName: "ddFilter"
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                verticalAlignment: TextInput.AlignVCenter
                color: Theme.bright
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                clip: true
                selectByMouse: true
                onTextEdited: {
                    dd.filterText = text
                    dd.hot = -1
                    dd.filterChanged(text)
                }
                Keys.onDownPressed: dd.step(1)
                Keys.onUpPressed: dd.step(-1)
                Keys.onReturnPressed: dd.enter()
                Keys.onEnterPressed: dd.enter()
                Keys.onEscapePressed: dd.close()
            }
        }
        ListView {
            id: list
            objectName: "ddList"
            width: parent.width
            height: Math.min(contentHeight, dd.maxCardHeight - 10 - (dd.filtering ? 32 : 0))
            interactive: contentHeight > height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: dd.entries
            delegate: Item {
                id: item
                required property int index
                required property var modelData
                readonly property bool group: modelData.group !== undefined
                readonly property bool cur: !group && modelData.current === true
                readonly property bool off: !group && modelData.off === true
                readonly property bool dimmed: !group && modelData.dim === true
                width: ListView.view.width
                height: 28

                Row {
                    visible: item.group
                    x: 6
                    y: 6
                    height: 18
                    spacing: 8
                    AppText {
                        id: gtext
                        height: parent.height
                        text: item.group ? item.modelData.group : ""
                        font.pixelSize: Theme.fontSmall
                        font.letterSpacing: 0.6
                        color: Theme.faint
                    }
                    Rectangle {
                        y: 9
                        width: item.width - gtext.width - 28
                        height: 1
                        color: Theme.divider
                    }
                }
                Rectangle {
                    visible: !item.group && !item.off && (hover.hovered || dd.hot === item.index)
                    anchors.fill: parent
                    radius: Theme.rRow
                    color: dd.onCard ? Theme.hotOnPanel : Theme.lift2
                }
                Rectangle {
                    visible: item.cur
                    x: 4
                    y: 7
                    width: 2
                    height: parent.height - 14
                    radius: 1
                    color: Theme.bright
                }
                AppText {
                    visible: !item.group
                    objectName: "ddItem" + item.index
                    x: 14
                    height: parent.height
                    width: item.width - 28 - note.width
                    elide: Text.ElideRight
                    text: item.group ? "" : item.modelData.text
                    color: item.off ? Theme.faint : (item.cur || hover.hovered || dd.hot === item.index ? Theme.bright : (item.dimmed ? Theme.dim : Theme.text))
                }
                AppText {
                    id: note
                    visible: !item.group
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    height: parent.height
                    text: !item.group && item.modelData.note !== undefined ? item.modelData.note : ""
                    color: Theme.dim
                }
                HoverHandler { id: hover; enabled: !item.group && !item.off; cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: !item.group && !item.off; onTapped: dd.pick(item.index) }
            }
        }
    }
    Keys.onDownPressed: step(1)
    Keys.onUpPressed: step(-1)
    Keys.onReturnPressed: enter()
    Keys.onEnterPressed: enter()
}
