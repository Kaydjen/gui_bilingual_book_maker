pragma ComponentBehavior: Bound
import QtQuick
import Novel

// What an export did (8.5, 9.9): the file name (the user's data, bright), the facts dim (`54 chapters · 0.9 MB`), or the reason in
// plain words; `Close | Show in folder`, `Close | Try again`, or `Close` alone when no file was written. A fact about chapters that
// were left out is dim, not red.
Panel {
    id: panel

    property var exp: null
    readonly property var info: exp.panelData
    readonly property bool mine: ["ok", "error", "nothing"].indexOf(exp.panel) >= 0

    cardItem.objectName: "exCard"
    closeButton.objectName: "exClose"
    actionButton.objectName: "exAction"
    title: info.title || "Export"
    closeText: "Close"
    actionText: exp.panel === "ok" ? "Show in folder" : (exp.panel === "error" ? "Try again" : "")
    panelWidth: 430
    onAccepted: exp.panelOk()
    onCloseRequested: if (mine) exp.panelClose()

    Column {
        width: parent.width
        spacing: 8
        AppText {
            objectName: "exFile"
            visible: text !== ""
            width: parent.width
            wrapMode: Text.WrapAnywhere
            text: panel.mine ? (panel.info.file || "") : ""
            color: Theme.bright
            font.pixelSize: Theme.fontTitle
        }
        AppText {
            objectName: "exFacts"
            width: parent.width
            wrapMode: Text.Wrap
            lineHeight: 1.3
            text: panel.mine ? (panel.info.facts || "") : ""
            color: Theme.dim
        }
        AppText {
            objectName: "exLeft"
            visible: text !== ""
            width: parent.width
            text: panel.mine ? (panel.info.left || "") : ""
            color: Theme.dim
            TipArea { tip: panel.info.tip || "" }
        }
    }
    Connections {
        target: panel.exp
        function onPanelChanged() {
            if (panel.mine)
                panel.open()
            else if (panel.visible)
                panel.close()
        }
    }
}
