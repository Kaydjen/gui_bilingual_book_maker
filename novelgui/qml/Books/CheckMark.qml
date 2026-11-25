import QtQuick
import Novel

// The box of a row or of the table head: empty, checked, or (head only) a dash.
Item {
    id: box

    property bool checked: false
    property bool dash: false
    property bool hot: false

    width: 16
    height: 16

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: box.checked ? Theme.bright : (box.hot ? Theme.lift : "transparent")
        border.width: 1
        border.color: box.checked ? Theme.bright : (box.dash || box.hot ? Theme.dim : Theme.faint)
    }
    AppText {
        visible: box.checked
        anchors.centerIn: parent
        text: "✓"
        font.family: Theme.symbolFamily
        font.pixelSize: 11
        font.bold: true
        color: Theme.bg
    }
    Rectangle {
        visible: box.dash && !box.checked
        anchors.centerIn: parent
        width: 8
        height: 2
        color: Theme.text
    }
}
