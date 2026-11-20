import QtQuick
import Novel
import Shell

// A panel with the things that open over it: a flat button, a list, a tooltip, a switch, a message with its button.
AppRoot {
    id: root

    Rectangle {
        anchors.fill: parent
        color: Theme.pane
    }
    Panel {
        id: panel
        objectName: "panel"
        title: "Panel"
        actionText: "Go"
        Pill { objectName: "inTip"; text: "Tip"; tip: "A tip over a panel" }
        Switch { objectName: "swOn"; y: 40; checked: true }
        Switch { objectName: "swOff"; x: 60; y: 40; checked: false }
        Menu {
            id: menu
            objectName: "menu"
            parent: panel
            items: [{ text: "One", id: "one" }, { text: "Two", id: "two" }]
        }
    }
    Toast {
        id: toast
        objectName: "toast"
    }
    Component.onCompleted: Qt.callLater(function () {
        panel.open()
        if (fake.menu === true)
            menu.openAt(500, 200)
        if (fake.toast === true)
            toast.show("A message over the panel")
    })
}
