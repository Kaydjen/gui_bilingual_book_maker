import QtQuick
import QtQuick.Window

// qmllint disable unqualified

Window {
    id: root
    objectName: "shell"
    width: 1100
    height: 720
    minimumWidth: 640
    minimumHeight: 420
    title: "Novel"
    color: "#111111"
    visible: false

    Rectangle {
        id: bannerBar
        objectName: "bannerBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: shell.bannerVisible ? 36 : 0
        color: "#1b1b1b"
        clip: true

        Text {
            objectName: "banner"
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 16
            text: shell.bannerVisible ? shell.bannerText : ""
            color: "#d8d8d8"
            font.pixelSize: 14
        }
    }
}
