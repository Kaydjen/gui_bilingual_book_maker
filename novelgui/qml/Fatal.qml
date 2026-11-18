import QtQuick
import QtQuick.Window
import "Novel"

// qmllint disable unqualified
// The last-resort panel (its own engine, the Novel module is imported by directory so no import path is needed).
Window {
    id: root
    objectName: "fatal"
    width: 560
    height: 300
    title: "Novel"
    color: Theme.bg
    visible: false

    Column {
        anchors.fill: parent
        anchors.margins: 28
        spacing: 14

        AppText {
            objectName: "fatalHeading"
            text: "The app could not start"
            color: Theme.bright
            font.pixelSize: 22
        }
        AppText {
            objectName: "fatalReason"
            width: parent.width
            text: fatal.firstLine
            color: Theme.dim
            font.pixelSize: Theme.fontTitle
            wrapMode: Text.Wrap
            maximumLineCount: 5
            elide: Text.ElideRight
        }
    }

    Row {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 28
        spacing: 12

        Pill {
            objectName: "copyButton"
            text: "Copy details"
            onClicked: fatal.copyDetails()
        }
        Pill {
            objectName: "logButton"
            text: "Open log"
            onClicked: fatal.openLog()
        }
        Pill {
            objectName: "quitButton"
            text: "Quit"
            kind: "main"
            onClicked: fatal.quit()
        }
    }
}
