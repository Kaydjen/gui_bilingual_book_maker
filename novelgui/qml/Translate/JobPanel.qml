pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The confirmations of Translate (9.12, 13.12): Replace the job?, Queue and replace the job?, Discard the job?, Replace the queued
// item?. The text comes as parts (`bright` = the name of the user's data); the view-model closes the panel itself as Cancel when
// its subject changed underneath.
Panel {
    id: panel

    property var translate: null
    readonly property var info: translate.panelData
    readonly property bool mine: ["replace", "queueReplace", "discard", "replaceItem"].indexOf(translate.panel) >= 0

    function plain(t) {
        return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }
    function html(parts) {
        var out = ""
        for (var i = 0; i < parts.length; ++i) {
            var p = parts[i]
            if (p.text === "\n")
                out += "<br>"
            else
                out += p.bright ? "<span style=\"color:" + Theme.bright + "\">" + plain(p.text) + "</span>" : plain(p.text)
        }
        return out
    }

    cardItem.objectName: "jobCard"
    closeButton.objectName: "jobCancel"
    actionButton.objectName: "jobOk"
    title: info.title || "Confirm"
    closeText: info.cancel || "Cancel"
    actionText: info.ok || "OK"
    panelWidth: 450
    onAccepted: translate.panelOk()
    onCloseRequested: if (mine) translate.panelCancel()

    AppText {
        objectName: "jobText"
        width: parent.width
        height: implicitHeight
        wrapMode: Text.Wrap
        textFormat: Text.RichText
        lineHeight: 1.35
        text: panel.mine ? panel.html(panel.info.parts || []) : ""
        color: Theme.dim
    }
    Connections {
        target: panel.translate
        function onPanelChanged() {
            if (panel.mine)
                panel.open()
            else if (panel.visible)
                panel.close()
        }
    }
}
