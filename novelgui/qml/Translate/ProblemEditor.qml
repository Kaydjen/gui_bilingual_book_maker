pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The row editor under the problem list (7.16): the source on the left, the translation on the right, typed in place; then
// Retry / Keep original / Ignore on the left and Save on the right. They act on the selected row.
Item {
    id: ed

    property var translate: null
    readonly property var info: translate.editor
    readonly property int key: info.open === true ? info.index : -1
    readonly property bool can: info.canResolve !== false
    readonly property real half: (width - 10) / 2

    implicitHeight: 134

    property bool loading: false

    // the row picked: its own text (what was typed there before, or the translation); a reload of the list that keeps the row
    // keeps the key and so the text being typed
    function load() {
        loading = true
        edit.text = info.text || ""
        loading = false
    }
    onKeyChanged: load()
    Component.onCompleted: load()

    Rectangle {
        objectName: "problemSourceBox"
        y: 10
        width: ed.half
        height: 84
        radius: 8
        color: Theme.pane
        Rectangle {
            x: 8
            width: parent.width - 16
            height: 1
            color: Theme.hairline
        }
        Flickable {
            anchors.fill: parent
            anchors.margins: 8
            contentHeight: sourceText.height
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            ReadText {
                id: sourceText
                objectName: "problemSourceText"
                width: parent.width
                leading: 1.25
                plain: ed.info.source || ""
                color: Theme.text
            }
        }
    }
    Rectangle {
        objectName: "problemEditBox"
        x: ed.half + 10
        y: 10
        width: ed.half
        height: 84
        radius: 8
        color: Theme.pane
        border.width: 1
        border.color: edit.activeFocus ? Theme.fieldFocus : "#2a2a2a"
        MouseArea {
            // the margin around the text: a click there types at the end
            anchors.fill: parent
            cursorShape: Qt.IBeamCursor
            onPressed: {
                edit.forceActiveFocus()
                edit.cursorPosition = edit.length
            }
        }
        Flickable {
            id: flick
            anchors.fill: parent
            anchors.margins: 8
            contentHeight: edit.implicitHeight
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            TextEdit {
                id: edit
                objectName: "problemEdit"
                width: flick.width
                height: Math.max(implicitHeight, flick.height)
                wrapMode: TextEdit.Wrap
                color: Theme.bright
                selectionColor: Theme.s4
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                selectByMouse: true
                onTextChanged: if (!ed.loading && ed.key >= 0) ed.translate.problemDraft(text)       // kept per row by the view-model
                onCursorRectangleChanged: {
                    if (cursorRectangle.y < flick.contentY)
                        flick.contentY = cursorRectangle.y
                    else if (cursorRectangle.y + cursorRectangle.height > flick.contentY + flick.height)
                        flick.contentY = cursorRectangle.y + cursorRectangle.height - flick.height
                }
                Keys.onPressed: event => {
                    Tips.dismiss()
                    event.accepted = false
                }
                MouseArea {
                    // the empty space below the text: the cursor goes to the end of the text
                    y: edit.contentHeight
                    width: parent.width
                    height: Math.max(0, parent.height - y)
                    cursorShape: Qt.IBeamCursor
                    onPressed: {
                        edit.forceActiveFocus()
                        edit.cursorPosition = edit.length
                    }
                }
            }
        }
    }
    Item {
        y: 104
        width: parent.width
        height: Theme.pillHeight

        Row {
            spacing: 8
            Pill {
                objectName: "problemRetry"
                text: "Retry"
                tip: ed.translate.tips.problemRetry
                onClicked: ed.translate.retryProblem()
            }
            Pill {
                objectName: "problemKeep"
                kind: ed.can ? "flat" : "off"
                text: "Keep original"
                tip: ed.can ? ed.translate.tips.problemKeep : ed.translate.tips.problemBusy
                onClicked: ed.translate.keepProblem()
            }
            Pill {
                objectName: "problemIgnore"
                visible: ed.info.finding === true
                kind: ed.can ? "flat" : "off"
                text: "Ignore"
                tip: ed.can ? ed.translate.tips.problemIgnore : ed.translate.tips.problemBusy
                onClicked: ed.translate.ignoreProblem()
            }
        }
        Pill {
            objectName: "problemSave"
            anchors.right: parent.right
            kind: ed.can ? "" : "off"
            text: "Save"
            tip: ed.can ? ed.translate.tips.problemSave : ed.translate.tips.problemBusy
            onClicked: ed.translate.saveProblem(edit.text)
        }
    }
}
