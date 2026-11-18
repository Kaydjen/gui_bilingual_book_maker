pragma ComponentBehavior: Bound
import QtQuick

// The round `•••` button that hangs beside the bottom bar (mock .sat), or any round lifted button.
Item {
    id: sat

    property string text: "•••"
    property var tip: ""
    readonly property bool hovered: hover.hovered
    signal clicked()

    implicitWidth: Theme.satSize
    implicitHeight: Theme.satSize
    activeFocusOnTab: true

    Surface {
        anchors.fill: parent
        level: 2
        radius: width / 2
        color: sat.hovered ? Theme.lift2 : Theme.lift
    }
    AppText {
        anchors.centerIn: parent
        text: sat.text
        font.bold: true
        font.letterSpacing: -1
        color: sat.hovered ? Theme.bright : Theme.dim
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: sat.clicked() }
    TipArea { tip: sat.tip }
    FocusRing { target: sat; inner: sat.width / 2 }
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()
}
