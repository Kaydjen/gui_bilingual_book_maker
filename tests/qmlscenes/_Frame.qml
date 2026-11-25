import QtQuick
import QtQuick.Window

// The window the harness puts every scene into (a real QML Window, like the application shell).
Window {
    id: frame
    objectName: "frame"
    color: "#000000"
    visible: false

    Loader {
        anchors.fill: parent
        source: harnessScene
    }
}
