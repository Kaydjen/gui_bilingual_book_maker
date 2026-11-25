pragma ComponentBehavior: Bound
import QtQuick
import Novel

// First start / library gone (9.11): one centred column on Books: the heading, the path in a field with a folder icon at
// its right (opens the chooser), `Create` in red text under it.
Item {
    id: first

    property var app: null
    property alias path: pathInput.text

    function create() {
        app.useFolder(pathInput.text)
    }
    Component.onCompleted: pathInput.text = app.defaultPath
    Connections {
        target: first.app
        function onPickedChanged() {
            pathInput.text = first.app.pickedPath
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 14
        AppText {
            objectName: "firstHeading"
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Choose a folder for your books"
            font.pixelSize: 17
            font.weight: Font.DemiBold
            color: Theme.bright
        }
        Inset {
            id: well
            objectName: "firstPath"
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(460, first.width - 48)
            height: 34
            edge: pathInput.activeFocus ? Theme.fieldFocus : Theme.fieldLine
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.IBeamCursor
                onPressed: pathInput.forceActiveFocus()
            }
            TextInput {
                id: pathInput
                objectName: "firstPathInput"
                anchors.fill: parent
                anchors.leftMargin: 34
                anchors.rightMargin: 34
                verticalAlignment: TextInput.AlignVCenter
                horizontalAlignment: TextInput.AlignHCenter
                color: Theme.bright
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                clip: true
                selectByMouse: true
                Keys.onReturnPressed: first.create()
            }
            Item {
                id: chooser
                objectName: "firstChooser"
                anchors.right: parent.right
                width: 34
                height: parent.height
                FolderIcon {
                    anchors.centerIn: parent
                    color: chooseHover.hovered ? Theme.bright : Theme.dim
                }
                HoverHandler { id: chooseHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: first.app.chooseFolder("") }
                TipArea { tip: first.app.tips.firstPath }
            }
        }
        Pill {
            objectName: "firstCreate"
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Create"
            kind: pathInput.text.trim() === "" ? "off" : "accent"
            tip: first.app.tips.firstCreate
            onClicked: first.create()
        }
    }
}
