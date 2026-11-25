pragma ComponentBehavior: Bound
import QtQuick

// A top-row control (mock .ctl): a dim name and the current value with a small arrow, optionally an edit segment.
// `red` colours the value (a problem to act on), `off` greys it, `progress` (0..1) draws a thin line along the bottom.
Item {
    id: ctl

    property string name: ""
    property string value: ""
    property string editText: ""
    property bool red: false
    property bool off: false
    property bool arrow: true
    property bool bright: false
    property real progress: -1
    property var tip: ""
    property var editTip: ""
    signal clicked()
    signal editClicked()

    implicitWidth: main.implicitWidth + (editText !== "" ? edit.implicitWidth + 1 : 0)
    implicitHeight: 30

    Surface {
        id: face
        anchors.fill: parent
        level: ctl.off ? 0 : 1
        color: ctl.off ? Theme.pillOff : Theme.pillFill(Theme.onPanel(ctl), false)
        clip: false
    }
    Item {
        anchors.fill: parent
        clip: true

        Rectangle {
            visible: !ctl.off && mainHover.hovered
            width: main.width
            height: parent.height
            color: Theme.pillFill(Theme.onPanel(ctl), true)
            radius: Theme.rControl
        }
        Rectangle {
            visible: !ctl.off && ctl.editText !== "" && editHover.hovered
            x: edit.x
            width: edit.width
            height: parent.height
            color: Theme.pillFill(Theme.onPanel(ctl), true)
        }
        Rectangle {
            visible: ctl.progress >= 0
            x: 0
            y: parent.height - 2
            width: parent.width * Math.max(0, Math.min(1, ctl.progress))
            height: 2
            color: Theme.dim
        }
    }
    Row {
        id: main
        objectName: ctl.objectName + "Main"
        height: parent.height
        leftPadding: 12
        rightPadding: 12
        spacing: 6
        AppText {
            height: parent.height
            visible: ctl.name !== ""
            text: ctl.name
            color: ctl.off ? Theme.faint : Theme.dim
        }
        AppText {
            objectName: ctl.objectName + "Value"
            height: parent.height
            text: ctl.value
            color: ctl.off ? Theme.faint : (ctl.red ? Theme.accent : (mainHover.hovered || ctl.bright ? Theme.bright : Theme.text))
        }
        AppText {
            visible: ctl.arrow
            height: parent.height
            text: "▾"
            font.pixelSize: 10
            color: ctl.off ? Theme.faint : Theme.dim
        }
        HoverHandler { id: mainHover; cursorShape: ctl.off ? Qt.ArrowCursor : Qt.PointingHandCursor }
        TapHandler { enabled: !ctl.off; onTapped: ctl.clicked() }
    }
    Rectangle {
        visible: ctl.editText !== ""
        x: main.width
        width: 1
        height: parent.height
        color: Theme.onPanel(ctl) ? Theme.panel : Theme.lift2
    }
    AppText {
        id: edit
        objectName: ctl.objectName + "Edit"
        visible: ctl.editText !== ""
        x: main.width + 1
        height: parent.height
        leftPadding: 11
        rightPadding: 11
        text: ctl.editText
        color: ctl.off ? Theme.faint : (editHover.hovered ? Theme.bright : Theme.dim)
        HoverHandler { id: editHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { enabled: !ctl.off; onTapped: ctl.editClicked() }
        TipArea { tip: ctl.editTip }
    }
    TipArea {
        anchors.fill: undefined
        width: main.width
        height: parent.height
        tip: ctl.tip
    }
    FocusRing { target: ctl; inner: Theme.rControl }
}
