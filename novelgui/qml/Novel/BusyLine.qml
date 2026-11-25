pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

// A thin line: value < 0 = a segment running along it (loading, 10.1); value 0..1 = it fills.
// The running segment is the only ambient motion and stops when the window is hidden, minimized or inactive.
Item {
    id: line

    property real value: -1
    property bool active: true
    property color trackColor: "transparent"
    property color fillColor: Theme.dim

    implicitHeight: 2
    clip: true

    Rectangle {
        anchors.fill: parent
        color: line.trackColor
    }
    Rectangle {
        visible: line.value >= 0
        width: parent.width * Math.min(1, Math.max(0, line.value))
        height: parent.height
        radius: height / 2
        color: line.fillColor
    }
    Rectangle {
        id: runner
        objectName: "busyRunner"
        visible: line.value < 0
        x: -width
        width: parent.width * 0.3
        height: parent.height
        color: line.fillColor

        XAnimator on x {
            from: -runner.width
            to: line.width
            duration: 1100
            loops: Animation.Infinite
            running: Visual.live && line.visible && line.value < 0 && line.active
        }
    }
    Component.onCompleted: Visual.attach(Window.window)
    Window.onWindowChanged: Visual.attach(Window.window)
}
