pragma ComponentBehavior: Bound
import QtQuick
import Novel
import Books
import Terms
import Translate
import Export

// The content of the main window: header, ONE screen at a time (placeholders for steps 5-8), the first-start block, the
// panels (settings, closing, library not found), the message panel and the second-start notice. Everything it shows
// comes from the view-models; it keeps no state of its own beyond what a panel being open needs.
AppRoot {
    id: root

    property var app: null
    property var vm: null
    property var log: null
    property var frame: null
    property var shell: null
    property var books: null
    property var add: null
    property var reader: null
    property var terms: null
    property var translate: null
    property var exporter: null
    property bool forceButtons: false
    readonly property bool ready: app !== null && app.libraryState === "ready"

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }
    Header {
        id: header
        objectName: "header"
        width: parent.width
        app: root.app
        frame: root.frame
        forceButtons: root.forceButtons
        translate: root.translate
        onGearClicked: root.app.openSettings()
    }
    Rectangle {
        id: pane
        objectName: "pane"
        x: 16
        y: header.height
        width: parent.width - 32
        height: parent.height - header.height - 16
        radius: Theme.rPane
        // Books draws its own two panes on the black window (mock .pane); the other screens sit in this one
        color: (root.app.screen === "books" || root.app.screen === "translate") && root.ready ? "transparent" : Theme.pane
        clip: true

        Item {
            objectName: "screen_books"
            anchors.fill: parent
            visible: root.app.screen === "books"
            BooksScreen {
                objectName: "booksScreen"
                anchors.fill: parent
                visible: root.ready
                books: root.books
                app: root.app
            }
            FirstStart {
                objectName: "firstStart"
                anchors.fill: parent
                visible: !root.ready
                app: root.app
            }
        }
        Item {
            objectName: "screen_terms"
            anchors.fill: parent
            visible: root.app.screen === "terms"
            TermsScreen {
                objectName: "termsScreen"
                anchors.fill: parent
                visible: root.ready
                terms: root.terms
                app: root.app
            }
        }
        Item {
            objectName: "screen_translate"
            anchors.fill: parent
            visible: root.app.screen === "translate"
            TranslateScreen {
                objectName: "translateScreen"
                anchors.fill: parent
                visible: root.ready && !root.reader.isOpen
                translate: root.translate
                app: root.app
            }
            ReaderTab {
                objectName: "readerScreen"
                anchors.fill: parent
                visible: root.reader.isOpen
                reader: root.reader
            }
        }
        Item {
            objectName: "screen_export"
            anchors.fill: parent
            visible: root.app.screen === "export"
            ExportScreen {
                objectName: "exportScreen"
                anchors.fill: parent
                visible: root.ready
                exp: root.exporter
                app: root.app
            }
        }
    }

    // the second start: the window pulses once and says so under the header for a few seconds (14.9)
    Surface {
        id: notice
        objectName: "bannerBar"
        visible: root.shell !== null && root.shell.bannerVisible
        anchors.horizontalCenter: parent.horizontalCenter
        y: header.height + 6
        z: 400
        level: 2
        radius: Theme.rMenu
        color: Theme.menu
        width: Math.min(parent.width - 40, bannerText.implicitWidth + 28)
        height: 34
        AppText {
            id: bannerText
            objectName: "banner"
            anchors.centerIn: parent
            width: parent.width - 28
            elide: Text.ElideRight
            text: root.shell !== null && root.shell.bannerVisible ? root.shell.bannerText : ""
            color: Theme.text
        }
    }

    DropFrame {
        objectName: "dropFrame"
        books: root.books
        enabled: root.ready && root.app.panel === "" && !root.app.settingsOpen
    }
    AddPanel {
        objectName: "addPanel"
        add: root.add
    }
    ImportPanel {
        objectName: "importPanel"
        terms: root.terms
    }
    MovePanel {
        objectName: "movePanel"
        books: root.books
    }
    JobPanel {
        objectName: "jobPanel"
        translate: root.translate
    }
    PromptPanel {
        objectName: "promptPanel"
        translate: root.translate
    }
    ResultPanel {
        objectName: "exportPanel"
        exp: root.exporter
    }
    SettingsPanel {
        objectName: "settingsPanel"
        app: root.app
        vm: root.vm
    }
    ClosingPanel {
        objectName: "closingPanel"
        app: root.app
    }
    Panel {
        id: missing
        objectName: "missingPanel"
        title: "Library not found"
        closeText: "Close"
        actionText: "Choose folder…"
        panelWidth: 430
        onAccepted: {
            close()
            root.app.chooseFolder("")
        }
        AppText {
            width: parent.width
            height: implicitHeight
            elide: Text.ElideMiddle
            text: root.app.libraryPath
            color: Theme.dim
            TruncTip {}
        }
    }
    Connections {
        target: root.app
        function onLibraryChanged() {
            if (root.app.libraryState === "missing")
                missing.open()
            else
                missing.close()
        }
    }
    Component.onCompleted: if (app.libraryState === "missing") missing.open()

    Toast {
        id: message
        objectName: "message"
        onDismissed: root.app.dismissMessage()
    }
    Connections {
        target: root.app
        function onMessageChanged() {
            if (root.app.message !== "")
                message.show(root.app.message)
            else
                message.dismiss()
        }
    }

    Shortcut {
        sequences: ["Ctrl+1"]
        enabled: root.app.panel === "" && !root.app.settingsOpen
        onActivated: root.app.goDigit(1)
    }
    Shortcut {
        sequences: ["Ctrl+2"]
        enabled: root.app.panel === "" && !root.app.settingsOpen
        onActivated: root.app.goDigit(2)
    }
    Shortcut {
        sequences: ["Ctrl+3"]
        enabled: root.app.panel === "" && !root.app.settingsOpen
        onActivated: root.app.goDigit(3)
    }
    Shortcut {
        sequences: ["Ctrl+4"]
        enabled: root.app.panel === "" && !root.app.settingsOpen
        onActivated: root.app.goDigit(4)
    }
}
