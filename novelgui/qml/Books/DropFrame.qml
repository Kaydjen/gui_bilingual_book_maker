pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import Novel

// Files dragged over the window (9.11): a dashed frame saying `Add 3 books`; dropping opens the Add panel. It fills the
// window area it is placed in, anywhere in the window (Books and every other screen); only .epub files count.
Item {
    id: drop

    property var books: null
    property int count: 0
    readonly property bool shown: count > 0

    anchors.fill: parent
    z: 450

    function title() {
        return count === 1 ? "Add book" : "Add " + count + " books"
    }

    DropArea {
        objectName: "dropArea"
        anchors.fill: parent
        onEntered: drag => {
            drop.count = drop.books.epubCount(drag.urls)
            if (drop.count === 0)
                drag.accepted = false
        }
        onExited: drop.count = 0
        onDropped: event => {
            drop.count = 0
            drop.books.dropped(event.urls)
        }
    }
    Rectangle {
        visible: drop.shown
        anchors.fill: parent
        color: Theme.veil
    }
    Shape {
        objectName: "dropOutline"
        visible: drop.shown
        anchors.fill: parent
        anchors.margins: 12
        ShapePath {
            strokeColor: Theme.dim
            strokeWidth: 2
            strokeStyle: ShapePath.DashLine
            dashPattern: [5, 4]
            fillColor: "transparent"
            startX: 12
            startY: 0
            PathLine { x: drop.width - 36; y: 0 }
            PathArc { x: drop.width - 24; y: 12; radiusX: 12; radiusY: 12 }
            PathLine { x: drop.width - 24; y: drop.height - 36 }
            PathArc { x: drop.width - 36; y: drop.height - 24; radiusX: 12; radiusY: 12 }
            PathLine { x: 12; y: drop.height - 24 }
            PathArc { x: 0; y: drop.height - 36; radiusX: 12; radiusY: 12 }
            PathLine { x: 0; y: 12 }
            PathArc { x: 12; y: 0; radiusX: 12; radiusY: 12 }
        }
    }
    AppText {
        objectName: "dropText"
        visible: drop.shown
        anchors.centerIn: parent
        text: drop.title()
        font.pixelSize: 18
        font.weight: Font.DemiBold
        color: Theme.bright
    }
}
