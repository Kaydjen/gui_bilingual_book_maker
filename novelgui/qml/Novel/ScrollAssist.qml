pragma ComponentBehavior: Bound
import QtQuick

// Wheel and middle-button scrolling for a Flickable / ListView (owner 2026-11-19: the default wheel felt sticky and slow,
// the middle button did nothing). Lay it over the view: a wheel notch glides `step` px in a short ease (a touchpad's
// pixel deltas move at once); the middle button pressed and dragged scrolls at a speed that grows with the distance
// from the press point; a short middle click leaves the scroll on until the next click. Left / right clicks and hover
// pass through to the rows.
MouseArea {
    id: assist

    property Flickable flickable: null
    property real step: 120                  // px per wheel notch (about 4 rows)
    property bool auto: false                // middle-button scrolling on
    property bool sticky: false              // ... after a short middle click, until the next click
    property real anchorX: 0
    property real anchorY: 0
    property real pointerY: 0
    property real pressedAt: 0
    readonly property real minY: flickable ? flickable.originY - flickable.topMargin : 0
    readonly property real maxY: flickable ? Math.max(minY, flickable.originY + flickable.contentHeight
                                                      + flickable.bottomMargin - flickable.height) : 0

    anchors.fill: flickable
    z: 50
    acceptedButtons: Qt.MiddleButton | (sticky ? Qt.LeftButton | Qt.RightButton : Qt.NoButton)
    hoverEnabled: sticky
    cursorShape: auto ? Qt.SizeVerCursor : Qt.ArrowCursor
    enabled: flickable !== null

    function clamp(y) {
        return Math.max(minY, Math.min(maxY, y))
    }
    function glide(dy) {
        var from = glideAnim.running ? glideAnim.to : flickable.contentY
        glideAnim.stop()
        glideAnim.from = flickable.contentY
        glideAnim.to = clamp(from + dy)
        glideAnim.start()
    }
    function speed() {
        var d = pointerY - anchorY
        var a = Math.max(0, Math.abs(d) - 8)
        return (d < 0 ? -1 : 1) * Math.pow(a, 1.35) / 6      // px per frame at 60 fps
    }
    function stopAuto() {
        auto = false
        sticky = false
    }

    onWheel: wheel => {
        if (wheel.pixelDelta.y !== 0) {
            glideAnim.stop()
            flickable.contentY = clamp(flickable.contentY - wheel.pixelDelta.y)
        } else if (wheel.angleDelta.y !== 0) {
            glide(-wheel.angleDelta.y / 120 * step)
        } else {
            wheel.accepted = false
        }
    }
    onPressed: mouse => {
        if (sticky) {
            stopAuto()
            return
        }
        anchorX = mouse.x
        anchorY = mouse.y
        pointerY = mouse.y
        pressedAt = Date.now()
        glideAnim.stop()
        auto = true
    }
    onPositionChanged: mouse => pointerY = mouse.y
    onReleased: mouse => {
        if (!auto)
            return
        if (Date.now() - pressedAt < 300 && Math.abs(mouse.y - anchorY) < 6)
            sticky = true
        else
            stopAuto()
    }
    onCanceled: stopAuto()
    onVisibleChanged: if (!visible) stopAuto()

    NumberAnimation {
        id: glideAnim
        target: assist.flickable
        property: "contentY"
        duration: 160
        easing.type: Easing.OutCubic
    }
    FrameAnimation {
        running: assist.auto && Visual.live
        onTriggered: assist.flickable.contentY = assist.clamp(assist.flickable.contentY + assist.speed() * frameTime * 60)
    }
    // the press point: a small ring with a dot, while the middle button scrolls
    Rectangle {
        visible: assist.auto
        x: assist.anchorX - 11
        y: assist.anchorY - 11
        width: 22
        height: 22
        radius: 11
        color: Theme.lift
        border.width: 1
        border.color: Theme.dim
        Rectangle {
            anchors.centerIn: parent
            width: 4
            height: 4
            radius: 2
            color: Theme.bright
        }
    }
}
