pragma ComponentBehavior: Bound
import QtQuick
import Novel

// Import (9.12, F5 Q4): ONE decision per file, `Goes to  Confirmed ▾` or `Not confirmed`; no per-term boxes. Above the buttons
// the two Terms tabs with their totals after the import; `Cancel | Import 214 terms`. Blocking is decided by the app.
Panel {
    id: panel

    property var terms: null
    readonly property var info: terms.importPanel

    cardItem.objectName: "importCard"
    closeButton.objectName: "importClose"
    actionButton.objectName: "importAction"
    title: info.title || "Import"
    closeText: "Cancel"
    actionText: info.action || "Import"
    panelWidth: 520
    onAccepted: terms.runImport()
    onCloseRequested: terms.cancelImport()

    function pickGoes(index, confirmed, anchorItem) {
        menu.fileIndex = index
        menu.items = [{ text: "Confirmed", kind: confirmed ? "check" : "" }, { text: "Not confirmed", kind: confirmed ? "" : "check" }]
        menu.openUnder(anchorItem)
    }

    Column {
        width: parent.width
        spacing: 12

        Rectangle {
            width: parent.width
            height: 34 + (panel.info.files ? panel.info.files.length : 0) * 30 + 6
            radius: 10
            color: Theme.s1
            Item {
                x: 12
                width: parent.width - 24
                height: 30
                AppText { height: parent.height; text: "File"; color: Theme.dim; font.pixelSize: Theme.fontSmall }
                AppText {
                    anchors.right: parent.right
                    anchors.rightMargin: 168
                    height: parent.height
                    text: "Terms"
                    color: Theme.dim
                    font.pixelSize: Theme.fontSmall
                }
                AppText {
                    anchors.right: parent.right
                    height: parent.height
                    text: "Goes to"
                    color: Theme.dim
                    font.pixelSize: Theme.fontSmall
                    TipArea { tip: panel.terms.tips.importWhere }
                }
            }
            Column {
                y: 32
                x: 12
                width: parent.width - 24
                Repeater {
                    model: panel.info.files || []
                    delegate: Item {
                        id: file
                        required property int index
                        required property var modelData
                        width: parent.width
                        height: 30
                        AppText {
                            objectName: "importName" + file.index
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.rightMargin: 230
                            height: parent.height
                            elide: Text.ElideMiddle
                            text: file.modelData.name
                            color: Theme.bright
                            TruncTip {}
                        }
                        AppText {
                            anchors.right: parent.right
                            anchors.rightMargin: 168
                            height: parent.height
                            text: String(file.modelData.terms)
                            color: Theme.dim
                        }
                        AppText {
                            id: goes
                            objectName: "importGoes" + file.index
                            anchors.right: parent.right
                            height: parent.height
                            text: (file.modelData.confirmed ? "Confirmed" : "Not confirmed") + " ▾"
                            color: goesHover.hovered ? Theme.bright : Theme.text
                            HoverHandler { id: goesHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: panel.pickGoes(file.index, file.modelData.confirmed, goes) }
                            TipArea { tip: panel.terms.tips.importGoes }
                        }
                    }
                }
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 22
            Row {
                spacing: 6
                AppText { text: "Confirmed"; color: Theme.dim }
                AppText { objectName: "importConfirmed"; text: String(panel.info.confirmed); color: Theme.text }
            }
            Row {
                spacing: 6
                AppText { text: "Not confirmed"; color: Theme.dim }
                AppText { objectName: "importUnconfirmed"; text: String(panel.info.unconfirmed); color: panel.info.unconfirmed ? Theme.text : Theme.faint }
            }
        }
    }
    Menu {
        id: menu
        objectName: "importMenu"
        parent: panel
        property int fileIndex: -1
        z: 900
        cardWidth: 150
        onPicked: (i, id) => panel.terms.setFileGoes(fileIndex, id === "Confirmed")
    }
    Connections {
        target: panel.terms
        function onImportChanged() {
            if (panel.terms.importPanel.open)
                panel.open()
            else
                panel.close()
        }
    }
}
