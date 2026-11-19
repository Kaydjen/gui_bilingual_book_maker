import QtQuick
import Novel
import Shell

// The log window's content.
AppRoot {
    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }
    LogView {
        anchors.fill: parent
        log: logVm
    }
}
