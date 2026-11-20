pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The three panels of closing: `Finishing the current requests` (9.11, with a countdown whose cap comes from the HTTP
// timeout), the wait message (14.6, `Cancel | Close`) and the first-time tray panel (14.24, `Quit | Hide to tray`).
// Esc dismisses; Enter is the main button.
FocusScope {
    id: panel

    property var app: null
    readonly property string kind: app ? app.panel : ""
    readonly property var info: app ? app.panelData : ({})
    property int secondsLeft: 0
    property real fraction: 0

    anchors.fill: parent
    visible: kind === "closing" || kind === "trayFirst"
    z: 650

    function left_clicked() {
        if (kind === "trayFirst")
            app.quitViaPanel()
        else if (info.kind === "running")
            app.quitNow()
        else
            app.closePanel()
    }
    function main() {
        if (kind === "trayFirst")
            app.hideToTray()
        else
            app.quitNow()
    }
    function restart() {
        if (!app || app.panel === "")
            return
        forceActiveFocus()
        secondsLeft = app.panelData.cap || 0
        fill.stop()
        fraction = 0
        if (secondsLeft > 0) {
            fill.duration = secondsLeft * 1000
            fill.restart()
        }
    }
    Connections {
        target: panel.app
        function onPanelChanged() {
            panel.restart()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.veil
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
        }
    }
    Surface {
        id: card
        objectName: "closingCard"
        anchors.centerIn: parent
        width: Math.min(430, panel.width - 40)
        height: 20 + col.height + 18 + foot.height + 18
        level: 3
        radius: Theme.rPanel
        color: Theme.panel
        MouseArea { anchors.fill: parent }

        Column {
            id: col
            x: 22
            y: 20
            width: parent.width - 44
            spacing: 8
            AppText {
                objectName: "closingTitle"
                visible: text !== ""
                width: parent.width
                text: panel.kind === "trayFirst" ? "" : (panel.info.title || "")
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                color: Theme.bright
            }
            AppText {
                objectName: "closingText"
                width: parent.width
                wrapMode: Text.Wrap
                text: panel.kind === "trayFirst" ? "Translation goes on in the tray. Click the tray icon to open the window."
                                                 : (panel.info.text || "")
                color: panel.kind === "trayFirst" ? Theme.text : Theme.dim
                lineHeight: 1.25
            }
            AppText {
                objectName: "closingText2"
                visible: text !== ""
                width: parent.width
                wrapMode: Text.Wrap
                text: panel.kind === "trayFirst" ? "" : (panel.info.text2 || "")
                color: Theme.dim
            }
            Row {
                visible: panel.kind === "closing" && panel.info.kind === "running"
                width: parent.width
                height: 18
                spacing: 10
                Rectangle {
                    objectName: "closingLine"
                    y: 8
                    width: parent.width - count.width - 10
                    height: 2
                    radius: 1
                    color: Theme.s3
                    Rectangle {
                        width: parent.width * panel.fraction
                        height: parent.height
                        radius: 1
                        color: Theme.dim
                    }
                }
                AppText {
                    id: count
                    objectName: "closingCount"
                    height: 18
                    text: "up to %1:%2".arg(Math.floor(panel.secondsLeft / 60)).arg(("0" + panel.secondsLeft % 60).slice(-2))
                    color: Theme.dim
                }
            }
        }
        Item {
            id: foot
            objectName: "closingFoot"
            x: 22
            width: parent.width - 44
            height: Theme.pillHeight
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 18
            Pill {
                objectName: "closingLeft"
                anchors.left: parent.left
                kind: "flat"
                text: panel.kind === "trayFirst" ? "Quit" : (panel.info.close || "")
                tip: panel.info.kind === "running" ? panel.app.tips.closeNow : ""
                onClicked: panel.left_clicked()
            }
            Pill {
                objectName: "closingMain"
                anchors.right: parent.right
                visible: text !== ""
                kind: "main"
                text: panel.kind === "trayFirst" ? "Hide to tray" : (panel.info.action || "")
                onClicked: panel.main()
            }
        }
    }
    NumberAnimation {
        id: fill
        target: panel
        property: "fraction"
        from: 0
        to: 1
    }
    Timer {
        interval: 1000
        repeat: true
        running: Visual.live && panel.visible && panel.secondsLeft > 0
        onTriggered: panel.secondsLeft = Math.max(0, panel.secondsLeft - 1)
    }
    Keys.onEscapePressed: app.closePanel()
    Keys.onReturnPressed: main()
}
