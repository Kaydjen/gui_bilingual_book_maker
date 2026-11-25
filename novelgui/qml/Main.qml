import QtQuick
import QtQuick.Window
import QtQuick.Dialogs
import Novel
import Shell

// qmllint disable unqualified

// The main window. The context objects (`shellVm`, `appVm`, `settingsVm`, `logVm`, `frameVm`) come from novelgui/runtime/assemble.py.
Window {
    id: root
    objectName: "shell"
    width: 1100
    height: 720
    minimumWidth: Theme.minWidth
    minimumHeight: Theme.minHeight
    title: "Novel"
    color: Theme.bg
    visible: false

    property string startUrl: ""

    function remember() {
        if (visible && visibility !== Window.Minimized && visibility !== Window.Hidden)
            appVm.geometryChanged(x, y, width, height, visibility === Window.Maximized)
    }
    onXChanged: remember()
    onYChanged: remember()
    onWidthChanged: remember()
    onHeightChanged: remember()
    onActiveChanged: if (active) appVm.windowActivated()
    onClosing: close => {
        close.accepted = false
        appVm.requestClose()
    }

    ShellRoot {
        anchors.fill: parent
        app: appVm
        vm: settingsVm
        log: logVm
        frame: frameVm
        shell: shellVm
    }

    Loader {
        id: folderLoader
        active: false
        sourceComponent: FolderDialog {
            currentFolder: root.startUrl
            onAccepted: appVm.folderChosen(selectedFolder.toString())
        }
        // qmllint disable missing-property
        onLoaded: item.open()
        // qmllint enable missing-property
    }
    Connections {
        target: appVm
        function onFolderDialogRequested(start) {
            root.startUrl = "file:///" + start.split("\\").join("/")
            if (folderLoader.active)
                folderLoader.item.open()    // qmllint disable missing-property
            else
                folderLoader.active = true
        }
    }

    Loader {
        active: appVm.logOpen
        sourceComponent: Window {
            width: 780
            height: 480
            visible: true
            title: "Novel · Log"
            color: Theme.bg
            onClosing: appVm.logClosed()
            AppRoot {
                anchors.fill: parent
                LogView {
                    anchors.fill: parent
                    log: logVm
                }
            }
        }
    }
}
