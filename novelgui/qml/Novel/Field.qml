pragma ComponentBehavior: Bound
import QtQuick

// A text field (window_spec 9.3, 9.4, 9.8): inset. Enter commits and leaves; a click elsewhere commits and leaves;
// Esc puts the old value back and leaves (never clears). A value `validate` refuses goes back (or, with keepOpen,
// stays for correction): red edge, one shake and the tooltip `invalidTip`.
// `validate(text)` returns true when the text is fine. `committed(text)` fires only for a changed, valid value.
Item {
    id: field

    property string value: ""
    property string placeholder: ""
    property var validate: null
    property string invalidTip: ""
    property bool keepOpen: false
    property bool multiline: false
    property alias input: textInput
    property bool invalid: false
    property bool editing: false             // set by the field itself, after a commit: the owner sees `editing` end only then
    property string old: ""
    property bool finishing: false
    signal committed(string text)
    signal rejected(string text)

    implicitWidth: 180
    implicitHeight: 28

    function ok(t) {
        return validate === null || validate(t)
    }
    function flash() {
        invalid = true
        shake.restart()
        if (invalidTip !== "")
            Tips.showNow(field, invalidTip, mapToItem(null, 0, height))
    }
    function leave() {
        finishing = true
        textInput.focus = false
        field.focus = false
        finishing = false
    }
    function refuse(t) {
        flash()
        rejected(t)
        if (!keepOpen) {
            textInput.text = old
            leave()
        }
    }
    // the owner may take this field away while it handles `committed` (a row rebuilt, a loader unloaded): what follows touches
    // the objects through locals only, never through a function of the destroyed context
    function commit() {
        var t = textInput.text
        if (!ok(t)) {
            refuse(t)
            return
        }
        invalid = false
        var me = field
        var input = textInput
        me.finishing = true
        if (t !== old) {
            value = t
            committed(t)
        }
        input.focus = me.focus = false
        me.finishing = false
    }
    function revert() {
        textInput.text = old
        invalid = false
        leave()
    }
    onValueChanged: if (!textInput.activeFocus) textInput.text = value
    Component.onCompleted: textInput.text = value

    Inset {
        anchors.fill: parent
        edge: field.invalid ? Theme.accent : (textInput.activeFocus ? Theme.fieldFocus : Theme.fieldLine)
    }
    MouseArea {
        // the 8 px margins of the box: a click there focuses the input and never falls to a row behind the field
        anchors.fill: parent
        cursorShape: Qt.IBeamCursor
        onPressed: textInput.forceActiveFocus()
    }
    TextInput {
        id: textInput
        objectName: field.objectName + "Input"
        x: 8
        width: parent.width - 16
        height: parent.height
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.bright
        selectionColor: Theme.s4
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
        clip: true
        selectByMouse: true
        activeFocusOnTab: true
        onActiveFocusChanged: {
            var me = field                  // the owner may destroy the field while it handles a commit: locals only after it
            if (activeFocus) {
                me.old = me.value
                me.invalid = false
                selectAll()
                me.editing = true
            } else {
                if (!me.finishing && text !== me.old)
                    me.commit()             // focus left by a click elsewhere or Tab
                me.editing = false
            }
        }
        Keys.onReturnPressed: event => {
            event.accepted = !field.multiline
            if (!field.multiline)
                field.commit()
        }
        Keys.onEscapePressed: event => {
            event.accepted = true
            field.revert()
        }
        Keys.onPressed: event => {
            Tips.dismiss()
            event.accepted = false
        }
    }
    AppText {
        visible: textInput.text === "" && !textInput.activeFocus
        x: 8
        height: parent.height
        text: field.placeholder
        color: Theme.faint
    }

    // one shake (9.8, 9.12): a short horizontal wiggle of the input text
    SequentialAnimation {
        id: shake
        NumberAnimation { target: textInput; property: "x"; to: 14; duration: 40 }
        NumberAnimation { target: textInput; property: "x"; to: 2; duration: 60 }
        NumberAnimation { target: textInput; property: "x"; to: 11; duration: 50 }
        NumberAnimation { target: textInput; property: "x"; to: 8; duration: 50 }
    }
}
