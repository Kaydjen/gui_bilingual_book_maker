pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The search of Terms (6.7): a `⌕` icon on the right that opens into a field (click, Ctrl+F or typing); `✕` on the right of
// the open field clears and closes it (= Esc); `0` inside on no hit. The text goes to the view-model, which debounces it.
Item {
    id: box

    property var terms: null
    readonly property bool open: terms.searchOpen
    property alias input: field

    function focusField(text) {
        terms.openSearch()
        field.forceActiveFocus()
        if (text !== undefined && text !== "") {
            field.text = text
            field.cursorPosition = text.length
            terms.setSearch(text)
        }
    }

    implicitWidth: open ? 240 : 32
    implicitHeight: 30
    Behavior on implicitWidth { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

    Inset {
        visible: box.open
        anchors.fill: parent
        edge: field.activeFocus ? Theme.fieldFocus : Theme.fieldLine
    }
    AppText {
        id: mag
        objectName: "searchIcon"
        x: 8
        width: 18
        height: parent.height
        text: "⌕"
        font.family: Theme.symbolFamily
        font.pixelSize: 16
        color: magHover.hovered || box.open ? Theme.bright : Theme.dim
    }
    HoverHandler { id: magHover; cursorShape: Qt.PointingHandCursor }
    TapHandler { enabled: !box.open; onTapped: box.focusField("") }
    TextInput {
        id: field
        objectName: "searchInput"
        visible: box.open
        x: 30
        width: parent.width - 30 - 52
        height: parent.height
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.bright
        selectionColor: Theme.s4
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
        clip: true
        selectByMouse: true
        onTextEdited: box.terms.setSearch(text)
        onActiveFocusChanged: if (!activeFocus && text === "") box.terms.closeSearch()
        Keys.onEscapePressed: {
            text = ""
            box.terms.closeSearch()
            box.parent.forceActiveFocus()
        }
    }
    AppText {
        objectName: "searchZero"
        visible: box.open && box.terms.searchZero
        anchors.right: clear.left
        anchors.rightMargin: 4
        height: parent.height
        text: "0"
        color: Theme.dim
    }
    AppText {
        id: clear
        objectName: "searchClear"
        visible: box.open
        anchors.right: parent.right
        anchors.rightMargin: 8
        height: parent.height
        text: "✕"
        font.family: Theme.symbolFamily
        color: clearHover.hovered ? Theme.bright : Theme.dim
        HoverHandler { id: clearHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: { field.text = ""; box.terms.closeSearch() } }
        TipArea { tip: box.terms.tips.clear }
    }
    TipArea { tip: box.open ? "" : box.terms.tips.search }
    Connections {
        target: box.terms
        function onViewChanged() {
            if (field.text !== box.terms.search && !field.activeFocus)
                field.text = box.terms.search
        }
    }
    Component.onCompleted: field.text = terms.search
}
