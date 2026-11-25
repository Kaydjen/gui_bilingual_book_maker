pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The content of the log window (14.4): lines `time · series · text`, oldest at the top, following the end while it is at
// the end; filter `Everything | Problems`, `Copy`, `Open folder`. Keys never appear in it.
Item {
    id: view

    property var log: null
    property bool follow: true

    Component.onCompleted: log.reload()

    Row {
        id: bar
        x: 16
        y: 14
        spacing: 10
        Segmented {
            objectName: "logFilter"
            model: ["Everything", "Problems"]
            currentIndex: view.log.filter
            onActivated: index => view.log.setFilter(index)
        }
        Pill {
            objectName: "logCopy"
            y: 1
            text: "Copy"
            tip: view.log.tips.copy
            onClicked: view.log.copy()
        }
        Pill {
            objectName: "logFolder"
            y: 1
            text: "Open folder"
            kind: "flat"
            onClicked: view.log.openFolder()
        }
    }
    Rectangle {
        x: 16
        y: bar.y + bar.height + 12
        width: parent.width - 32
        height: parent.height - y - 16
        radius: Theme.rPane
        color: Theme.pane
        clip: true

        ListView {
            id: list
            objectName: "logList"
            anchors.fill: parent
            anchors.margins: 8
            clip: true
            model: view.log.lines
            boundsBehavior: Flickable.StopAtBounds
            onMovementEnded: view.follow = atYEnd
            onCountChanged: if (view.follow) Qt.callLater(function () { list.positionViewAtEnd() })
            delegate: Item {
                id: line
                required property int index
                required property string when
                required property string series
                required property string text
                required property bool problem
                width: ListView.view.width
                height: 24
                AppText {
                    objectName: "logLine" + line.index
                    width: parent.width
                    height: parent.height
                    elide: Text.ElideRight
                    text: line.when + " · " + (line.series !== "" ? line.series + " · " : "") + line.text
                    color: line.problem ? Theme.bright : Theme.dim
                    font.family: "Consolas"
                    font.pixelSize: 12
                }
            }
        }
        ScrollAssist {
            flickable: list
        }
    }
}
