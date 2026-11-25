pragma ComponentBehavior: Bound
import QtQuick

// A message panel (mock toast): a small lifted card with a text and one button, centred in the area it is placed in.
Item {
    id: toast

    property string text: ""
    property string buttonText: "OK"
    signal dismissed()

    anchors.fill: parent
    visible: false
    z: 700

    function show(t) {
        text = t
        visible = true
    }
    function dismiss() {
        if (!visible)
            return
        visible = false
        dismissed()
    }

    MouseArea {
        anchors.fill: parent                // a click on the veil does not reach the screen below
        acceptedButtons: Qt.AllButtons
    }
    Surface {
        id: card
        objectName: "toastCard"
        anchors.centerIn: parent
        width: Math.min(420, Math.max(300, msg.implicitWidth + 40))
        height: msg.height + 16 + Theme.pillHeight + 32
        level: 3
        radius: 12
        color: Theme.lift2

        MouseArea { anchors.fill: parent }

        AppText {
            id: msg
            x: 20
            y: 16
            width: parent.width - 40
            height: implicitHeight
            text: toast.text
            wrapMode: Text.Wrap
            color: Theme.text
        }
        Pill {
            objectName: "toastButton"
            onLift: true
            anchors.right: parent.right
            anchors.rightMargin: 20
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            text: toast.buttonText
            onClicked: toast.dismiss()
        }
    }
}
