pragma ComponentBehavior: Bound
import QtQuick

// Top and bottom scroll fades laid over a scrolling pane (mock .fade / .fadetop): the bottom one shows while there is more
// below, the top one while the list is scrolled. Place it over the pane and give it the Flickable.
Item {
    id: fades

    property Flickable flickable: null
    property color color: Theme.pane
    property real bottomHeight: 70
    property real topHeight: 40
    property real topOffset: 0
    property real rightMargin: 0
    readonly property bool more: flickable !== null && flickable.contentHeight > flickable.height && !flickable.atYEnd
    readonly property bool scrolled: flickable !== null && !flickable.atYBeginning

    anchors.fill: parent
    enabled: false

    Rectangle {
        objectName: "fadeBottom"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.rightMargin: fades.rightMargin
        anchors.bottom: parent.bottom
        height: fades.bottomHeight
        opacity: fades.more ? 1 : 0
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(fades.color.r, fades.color.g, fades.color.b, 0) }
            GradientStop { position: 0.7; color: Qt.rgba(fades.color.r, fades.color.g, fades.color.b, 0.92) }
            GradientStop { position: 1; color: fades.color }
        }
        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
    }
    Rectangle {
        objectName: "fadeTop"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.rightMargin: fades.rightMargin
        anchors.top: parent.top
        anchors.topMargin: fades.topOffset
        height: fades.topHeight
        opacity: fades.scrolled ? 1 : 0
        gradient: Gradient {
            GradientStop { position: 0; color: fades.color }
            GradientStop { position: 0.45; color: Qt.rgba(fades.color.r, fades.color.g, fades.color.b, 0.85) }
            GradientStop { position: 1; color: Qt.rgba(fades.color.r, fades.color.g, fades.color.b, 0) }
        }
        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
    }
}
