pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

// A small spinner: a ring of dots of falling brightness turned by ONE RotationAnimator (render thread, no canvas).
Item {
    id: spinner

    property real size: 18
    property color color: Theme.dim
    property int dots: 8
    property bool active: true

    implicitWidth: size
    implicitHeight: size

    Item {
        id: ring
        anchors.fill: parent
        Repeater {
            model: spinner.dots
            delegate: Rectangle {
                required property int index
                readonly property real a: index * 2 * Math.PI / spinner.dots
                width: spinner.size / 5
                height: width
                radius: width / 2
                x: spinner.size / 2 + Math.sin(a) * (spinner.size / 2 - width / 2) - width / 2
                y: spinner.size / 2 - Math.cos(a) * (spinner.size / 2 - width / 2) - height / 2
                color: spinner.color
                opacity: 0.15 + 0.85 * index / spinner.dots
            }
        }
        RotationAnimator on rotation {
            from: 0
            to: 360
            duration: 900
            loops: Animation.Infinite
            running: Visual.live && spinner.visible && spinner.active
        }
    }
    Component.onCompleted: Visual.attach(Window.window)
    Window.onWindowChanged: Visual.attach(Window.window)
}
