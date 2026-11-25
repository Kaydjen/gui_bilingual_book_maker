pragma ComponentBehavior: Bound
import QtQuick
import Novel

// One of the three title-bar buttons (9.10): a glyph that brightens on hover, never red.
Item {
    id: btn

    property string glyph: ""
    property var tip: ""
    property bool hot: false            // the pointer is on it by the native hit test (the maximize button)
    readonly property bool hovered: hover.hovered || hot
    signal clicked()

    implicitWidth: 38
    implicitHeight: 32

    Rectangle {
        anchors.fill: parent
        radius: Theme.rControl
        color: Theme.lift2
        opacity: btn.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 100 } }
    }
    AppText {
        anchors.centerIn: parent
        text: btn.glyph
        font.pixelSize: 15
        font.family: Theme.symbolFamily
        color: btn.hovered ? Theme.bright : Theme.dim
    }
    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler { onTapped: btn.clicked() }
    TipArea { tip: btn.tip }
}
