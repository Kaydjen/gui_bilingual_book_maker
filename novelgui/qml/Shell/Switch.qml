pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The lifted switch of Settings: an inset track, a raised knob, bright when on.
Item {
    id: sw

    property bool checked: false
    property bool off: false
    signal toggled(bool value)

    implicitWidth: 34
    implicitHeight: 20

    Inset {
        objectName: sw.objectName !== "" ? sw.objectName + "Track" : ""
        anchors.fill: parent
        radius: 10
        color: sw.checked ? Theme.switchOn : "#0c0c0c"
        edge: "transparent"
    }
    Rectangle {
        x: sw.checked ? 16 : 2
        y: 2
        width: 16
        height: 16
        radius: 8
        color: sw.off ? Theme.s2 : (sw.checked ? Theme.bright : (hover.hovered ? "#3a3a3a" : "#2c2c2c"))
        Behavior on x { NumberAnimation { duration: 150 } }
    }
    HoverHandler { id: hover; cursorShape: sw.off ? Qt.ArrowCursor : Qt.PointingHandCursor }
    TapHandler { enabled: !sw.off; onTapped: sw.toggled(!sw.checked) }
}
