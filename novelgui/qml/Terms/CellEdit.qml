pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A cell turned into a field in place (9.12): Enter takes the text and leaves, Tab takes it and goes to the next cell, Esc
// returns the old value and leaves, a click elsewhere takes it. No panel, no Save button.
Item {
    id: ed

    property string value: ""
    property string tip: ""
    property bool done: false
    signal taken(string text)
    signal tabbed()
    signal finished()

    function finish(save, tab) {
        if (done)
            return
        done = true
        if (save && input.text !== value)
            taken(input.text)
        if (tab)
            tabbed()
        else
            finished()
    }
    Component.onCompleted: {
        input.text = value
        input.forceActiveFocus()
        input.selectAll()
    }

    Inset {
        anchors.fill: parent
        edge: Theme.fieldFocus
    }
    TextInput {
        id: input
        objectName: ed.objectName + "Input"
        x: 7
        width: parent.width - 14
        height: parent.height
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.bright
        selectionColor: Theme.s4
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
        clip: true
        selectByMouse: true
        onActiveFocusChanged: if (!activeFocus) ed.finish(true, false)
        Keys.onReturnPressed: ed.finish(true, false)
        Keys.onEnterPressed: ed.finish(true, false)
        Keys.onEscapePressed: ed.finish(false, false)
        Keys.onTabPressed: ed.finish(true, true)
    }
    TipArea { tip: ed.tip }
}
