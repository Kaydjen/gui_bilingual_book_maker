pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Queue tab (7.16 F7): the running or waiting job first, then the queued items, one per series.
Item {
    id: tab

    property var translate: null
    property alias list: view

    ListView {
        id: view
        objectName: "trQueueList"
        anchors.fill: parent
        anchors.topMargin: 6
        bottomMargin: 84
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: tab.translate.queueModel
        delegate: QueueRow {
            translate: tab.translate
        }
    }
    ScrollAssist {
        flickable: view
    }
    Fades {
        flickable: view
    }
}
