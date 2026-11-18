import QtQuick
import QtQuick.Controls
import QtQuick.Window

Window {
    id: root
    objectName: "fatal"
    width: 560
    height: 300
    title: "Novel"
    color: "#111111"
    visible: false

    Column {
        anchors.fill: parent
        anchors.margins: 28
        spacing: 14

        Text {
            objectName: "fatalHeading"
            text: "The app could not start"
            color: "#e8e8e8"
            font.pixelSize: 22
        }
        Text {
            objectName: "fatalReason"
            width: parent.width
            text: fatal.firstLine
            color: "#b0b0b0"
            font.pixelSize: 14
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

        Button {
            objectName: "copyButton"
            text: "Copy details"
            onClicked: fatal.copyDetails()
        }
        Button {
            objectName: "logButton"
            text: "Open log"
            onClicked: fatal.openLog()
        }
        Button {
            objectName: "quitButton"
            text: "Quit"
            onClicked: fatal.quit()
        }
    }
}
