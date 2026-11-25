pragma ComponentBehavior: Bound
import QtQuick

// A modal panel (window_spec 9.1, 9.2, 9.9): a FocusScope over a dimming veil that fills the area it is placed in.
// Foot rule: the closing button left, the action right. Esc closes (a field inside takes its own Esc first), Enter
// presses the main button (not inside a multi-line field), a press outside first commits the focused field, then closes.
FocusScope {
    id: panel

    property string title: ""
    property string closeText: "Cancel"
    property string actionText: ""
    property string actionKind: "main"
    property bool actionEnabled: true
    property bool sticky: false
    property bool panelSurface: true        // a menu or a list opened over the panel is a card on a card
    property real panelWidth: 440
    property real margin: 20
    default property alias content: inner.data
    property alias cardItem: card
    property alias closeButton: closeBtn
    property alias actionButton: actionBtn
    signal closeRequested()
    signal accepted()
    signal cancelled()                      // the closing BUTTON was pressed (Esc and a click outside only close)

    anchors.fill: parent
    visible: false
    z: 600

    function open() {
        keeper.remember()
        visible = true
        forceActiveFocus()
    }
    function close() {
        if (!visible)
            return
        visible = false
        closeRequested()
    }
    function cancel() {
        cancelled()
        close()
    }
    function accept() {
        if (!visible)
            return
        if (actionText !== "" && actionEnabled)
            accepted()
    }

    onVisibleChanged: if (!visible) keeper.restore()
    FocusKeeper {
        id: keeper
        owner: panel
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.veil
        opacity: panel.visible ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onPressed: card.forceActiveFocus()          // the field loses focus and commits
            onReleased: {
                if (!panel.sticky)
                    panel.close()               // closed on the release: a hidden veil would hand it to what lies under it
            }
        }
    }
    Surface {
        id: card
        objectName: "panelCard"
        property bool panelSurface: true
        anchors.centerIn: parent
        width: Math.min(panel.panelWidth, panel.width - 2 * panel.margin)
        height: Math.min(panel.height - 2 * panel.margin, 22 + head.height + inner.childrenRect.height + 16 + foot.height + 20)
        level: 3
        radius: Theme.rPanel
        color: Theme.panel
        opacity: panel.visible ? 1 : 0
        transform: Translate { y: panel.visible ? 0 : -4 }
        Behavior on opacity { NumberAnimation { duration: Theme.durPanel } }

        MouseArea { anchors.fill: parent }

        Item {
            x: 22
            y: 20
            width: parent.width - 44
            height: parent.height - 40

            AppText {
                id: head
                objectName: panel.objectName + "Title"
                width: parent.width
                height: panel.title !== "" ? implicitHeight + 14 : 0
                visible: panel.title !== ""
                text: panel.title
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                color: Theme.bright
            }
            Flickable {
                id: body
                objectName: card.objectName + "Body"
                y: head.height
                width: parent.width
                height: Math.min(inner.childrenRect.height, parent.height - head.height - 16 - foot.height)
                contentHeight: inner.childrenRect.height
                clip: true
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds
                Item {
                    id: inner
                    width: body.width
                }
            }
            Item {
                id: foot
                objectName: "panelFoot"
                anchors.bottom: parent.bottom
                width: parent.width
                height: Theme.pillHeight
                Pill {
                    id: closeBtn
                    objectName: "panelClose"
                    anchors.right: actionBtn.visible ? actionBtn.left : parent.right
                    anchors.rightMargin: actionBtn.visible ? 8 : 0
                    text: panel.closeText
                    kind: "flat"
                    onClicked: panel.cancel()
                }
                Pill {
                    id: actionBtn
                    objectName: "panelAction"
                    anchors.right: parent.right
                    visible: panel.actionText !== ""
                    text: panel.actionText
                    kind: panel.actionEnabled ? panel.actionKind : "off"
                    onClicked: panel.accept()
                }
            }
        }
    }
    Keys.onEscapePressed: close()
    Keys.onReturnPressed: accept()
    Keys.onEnterPressed: accept()
}
