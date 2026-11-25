pragma ComponentBehavior: Bound
import QtQuick
import Novel

// A lifted two-segment control (the Prompt control of Translate): a name that acts as a button, a hairline, a second action.
Item {
    id: seg

    property string name: ""
    property string action: ""
    property bool actionOff: false
    property var nameTip: ""
    property var actionTip: ""
    signal nameClicked()
    signal actionClicked()

    implicitWidth: nameText.implicitWidth + 24 + 1 + actionText.implicitWidth + 24
    implicitHeight: 30

    Surface {
        anchors.fill: parent
        level: 1
        color: Theme.pill
    }
    Item {
        anchors.fill: parent
        clip: true
        Rectangle {
            visible: nameHover.hovered
            width: nameText.width
            height: parent.height
            color: Theme.pillHover
        }
        Rectangle {
            visible: !seg.actionOff && actionHover.hovered
            x: actionText.x
            width: actionText.width
            height: parent.height
            color: Theme.pillHover
        }
    }
    AppText {
        id: nameText
        objectName: seg.objectName + "Name"
        height: parent.height
        leftPadding: 12
        rightPadding: 12
        text: seg.name
        color: nameHover.hovered ? Theme.bright : Theme.text
        HoverHandler { id: nameHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: seg.nameClicked() }
        TipArea { tip: seg.nameTip }
    }
    Rectangle {
        x: nameText.width
        width: 1
        height: parent.height
        color: Theme.lift2
    }
    AppText {
        id: actionText
        objectName: seg.objectName + "Action"
        x: nameText.width + 1
        height: parent.height
        leftPadding: 12
        rightPadding: 12
        text: seg.action
        color: seg.actionOff ? Theme.faint : (actionHover.hovered ? Theme.bright : Theme.dim)
        HoverHandler { id: actionHover; cursorShape: seg.actionOff ? Qt.ArrowCursor : Qt.PointingHandCursor }
        TapHandler { enabled: !seg.actionOff; onTapped: seg.actionClicked() }
        TipArea { tip: seg.actionTip }
    }
}
