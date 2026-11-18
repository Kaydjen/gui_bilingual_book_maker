pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

// Placeholder rows of a table that is loading. ONE shimmer for the whole block: a gradient strip clipped to the block
// and moved by one XAnimator; the gaps between the bars are covered by pane-coloured masks, so the bars are the only
// parts that show it. `cells` = widths of the bars as fractions of the width, repeated on every row.
Item {
    id: skel

    property int rows: 6
    property var cells: [0.08, 0.45, 0.2]
    property real rowHeight: Theme.rowHeight
    property real barHeight: 9
    property real padding: 14
    property real gap: 16
    property color maskColor: Theme.pane
    property color base: Theme.s2
    property color glint: "#242424"
    property bool active: true

    implicitHeight: rows * rowHeight

    // x / width of every bar of a row
    function bars() {
        var out = [], x = padding, avail = width - 2 * padding
        for (var i = 0; i < cells.length; ++i) {
            var w = Math.max(4, cells[i] * avail)
            out.push({ x: x, w: w })
            x += w + gap
        }
        return out
    }
    // the rectangles that hide everything except the bars
    function masks() {
        var out = [], b = bars(), pad = (rowHeight - barHeight) / 2
        for (var r = 0; r < rows; ++r) {
            var y = r * rowHeight
            out.push({ x: 0, y: y, w: width, h: pad })
            out.push({ x: 0, y: y + pad + barHeight, w: width, h: pad })
            var cx = 0
            for (var i = 0; i < b.length; ++i) {
                out.push({ x: cx, y: y + pad, w: b[i].x - cx, h: barHeight })
                cx = b[i].x + b[i].w
            }
            out.push({ x: cx, y: y + pad, w: width - cx, h: barHeight })
        }
        return out
    }

    Item {
        anchors.fill: parent
        clip: true

        Rectangle {
            anchors.fill: parent
            color: skel.base
        }
        Rectangle {
            id: shimmer
            objectName: "skeletonShimmer"
            x: -width
            width: skel.width / 3
            height: parent.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: skel.base }
                GradientStop { position: 0.5; color: skel.glint }
                GradientStop { position: 1; color: skel.base }
            }
            XAnimator on x {
                from: -shimmer.width
                to: skel.width
                duration: 1300
                loops: Animation.Infinite
                running: Visual.live && skel.visible && skel.active
            }
        }
        Repeater {
            model: skel.masks()
            delegate: Rectangle {
                required property var modelData
                x: modelData.x
                y: modelData.y
                width: modelData.w
                height: modelData.h
                color: skel.maskColor
            }
        }
    }
    Component.onCompleted: Visual.attach(Window.window)
    Window.onWindowChanged: Visual.attach(Window.window)
}
