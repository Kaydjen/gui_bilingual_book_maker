pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The prompt editor (9.2): a name and the text, `Cancel | Save`. Save is dim until something changed. Unsaved text stays as the
// draft of the next Edit: Esc and a click outside keep it, Cancel throws it away. `{language}` is the series' language.
Panel {
    id: panel

    property var translate: null
    readonly property var info: translate.panelData
    readonly property bool mine: translate.panel === "prompt"
    property string initName: ""
    property string initText: ""
    property string reason: ""
    property bool dropDraft: false
    readonly property bool changed: info.draft === true || nameField.value !== initName || bodyText !== initText
    property string bodyText: ""

    cardItem.objectName: "promptCard"
    closeButton.objectName: "promptCancel"
    actionButton.objectName: "promptSave"
    actionButton.tip: reason !== "" ? reason : (changed ? translate.tips.problemSave : translate.tips.promptNothing)
    title: "Prompt"
    closeText: "Cancel"
    actionText: "Save"
    actionEnabled: reason === "" && changed
    panelWidth: 720

    function load() {
        initName = info.name || ""
        initText = info.text || ""
        dropDraft = false
        nameField.value = initName
        body.text = initText
        bodyText = initText
        reason = translate.promptChanged(initName, initText)
    }
    function edited() {
        bodyText = body.text
        reason = translate.promptChanged(nameField.value, body.text)
    }
    onAccepted: translate.promptSave(nameField.value, body.text)
    onCancelled: dropDraft = true
    onCloseRequested: if (mine) translate.promptClosed(nameField.value, body.text, !dropDraft)

    Column {
        width: parent.width
        spacing: 10
        Row {
            width: parent.width
            spacing: 10
            AppText {
                width: 50
                height: 28
                text: "Name"
                color: Theme.dim
            }
            Field {
                id: nameField
                objectName: "promptName"
                width: parent.width - 60
                placeholder: "New prompt"
                keepOpen: true
                onCommitted: panel.edited()
                input.onTextEdited: {
                    nameField.value = input.text
                    panel.edited()
                }
            }
        }
        Inset {
            objectName: "promptBox"
            width: parent.width
            height: panel.width < 900 ? 250 : 340
            edge: body.activeFocus ? Theme.fieldFocus : Theme.fieldLine
            Flickable {
                id: flick
                anchors.fill: parent
                anchors.margins: 8
                contentHeight: body.implicitHeight
                clip: true
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds
                TextEdit {
                    id: body
                    objectName: "promptText"
                    width: flick.width
                    wrapMode: TextEdit.Wrap
                    color: Theme.bright
                    selectionColor: Theme.s4
                    font.family: "Consolas"
                    font.pixelSize: Theme.fontSize
                    selectByMouse: true
                    onTextChanged: panel.edited()
                    onCursorRectangleChanged: {
                        if (cursorRectangle.y < flick.contentY)
                            flick.contentY = cursorRectangle.y
                        else if (cursorRectangle.y + cursorRectangle.height > flick.contentY + flick.height)
                            flick.contentY = cursorRectangle.y + cursorRectangle.height - flick.height
                    }
                    TipArea { tip: panel.translate.tips.promptText }
                }
            }
        }
    }
    AppText {
        objectName: "promptDraft"
        visible: panel.info.draft === true
        parent: panel.cardItem
        anchors.right: parent.right
        anchors.rightMargin: 22
        y: 20
        height: 22
        text: "Draft"
        color: Theme.dim
        TipArea { tip: panel.translate.tips.promptDraft }
    }
    Connections {
        target: panel.translate
        function onPanelChanged() {
            if (panel.translate.panel === "prompt") {
                panel.load()
                panel.open()
            } else if (panel.visible) {
                panel.close()
            }
        }
    }
}
