pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Translate screen (7.16, style B): the top row on the black window, the tabs (only when there is more than Chapters), the pane with
// the chapter list / problems / queue / sample, the row editor under the problem list, and ONE floating bar at the bottom of the
// pane. Everything comes from the TranslateVM; this file holds only where things sit.
Item {
    id: screen

    property var translate: null
    property var app: null
    readonly property bool none: translate.view === "none"
    readonly property bool ready: translate.view === "ready"
    readonly property bool tabsShown: translate.tabs.length > 0
    readonly property real paneY: 50 + (tabsShown ? 28 : 0)
    readonly property bool editing: translate.tab === "problems" && translate.editor.open === true
    readonly property var segments: barSegments(translate.bar, translate.checkPercent)
    property string deleted: ""

    function barSegments(list, percent) {
        var out = []
        for (var i = 0; i < list.length; ++i) {
            var s = list[i]
            var kind = s.enabled === false ? "off" : (s.tone === "red" ? "accent" : (s.tone === "main" ? "main" : ""))
            out.push({ text: s.text, id: s.id, tip: s.tip, kind: kind, progress: s.id === "checking" ? percent : -1 })
        }
        return out
    }
    function openLanguage(anchorItem) {
        langLoader.active = true
        var drop = langLoader.item as DropDown
        drop.entries = translate.languageEntries("")
        drop.openUnder(anchorItem)
    }
    function openPrompts(anchorItem) {
        promptDrop.entries = translate.promptEntries()
        promptDrop.openUnder(anchorItem)
    }
    function openMenu(menu, items, anchorItem) {
        menu.items = items
        menu.openUnder(anchorItem)
    }

    TopRow {
        id: top
        objectName: "trTop"
        width: parent.width
        height: 46
        translate: screen.translate
        onToClicked: item => screen.openLanguage(item)
        onPromptClicked: item => screen.openPrompts(item)
        onTimeClicked: item => timePop.openRight(item)
    }
    TrTabs {
        id: tabs
        objectName: "trTabs"
        visible: screen.tabsShown
        y: 50
        translate: screen.translate
    }
    Rectangle {
        id: pane
        objectName: "trPane"
        y: screen.paneY
        width: parent.width
        height: parent.height - screen.paneY - (screen.editing ? editor.height : 0)
        radius: Theme.rPane
        color: Theme.pane
        Rectangle {
            x: Theme.rPane
            width: parent.width - 2 * Theme.rPane
            height: 1
            color: Theme.hairline
        }
    }
    Item {
        id: content
        y: pane.y
        width: pane.width
        height: pane.height
        visible: !screen.none

        ChapterTab {
            id: chapters
            objectName: "trChapterTab"
            anchors.fill: parent
            visible: screen.ready && screen.translate.tab === "chapters"
            translate: screen.translate
            onContextRequested: (i, rowItem) => {
                var p = rowItem.mapToItem(screen, 200, 15)
                rowMenu.rowIndex = i
                rowMenu.items = [{ text: "Read", id: "read", kind: rowItem.translated ? "" : "off", tip: rowItem.translated ? "" : screen.translate.tips.readOff }]
                rowMenu.openAt(p.x, p.y)
            }
        }
        ProblemsTab {
            objectName: "trProblemsTab"
            anchors.fill: parent
            visible: screen.translate.tab === "problems"
            translate: screen.translate
        }
        QueueTab {
            objectName: "trQueueTab"
            anchors.fill: parent
            visible: screen.translate.tab === "queue"
            translate: screen.translate
        }
        SampleTab {
            objectName: "trSampleTab"
            anchors.fill: parent
            visible: screen.translate.tab === "sample"
            translate: screen.translate
        }
        Skeleton {
            objectName: "trSkeleton"
            visible: screen.translate.view === "loading"
            y: 4
            x: 6
            width: parent.width - 12
            rows: Math.max(3, Math.floor(parent.height / Theme.rowHeight) - 1)
            cells: [0.3, 0.12]
            maskColor: Theme.pane
        }
        AppText {
            objectName: "trBroken"
            visible: screen.translate.view === "broken"
            anchors.centerIn: parent
            text: "The book cannot be read"
            color: Theme.dim
        }
    }
    AppText {
        objectName: "trNoSeries"
        visible: screen.none
        x: 0
        y: pane.y
        width: pane.width
        height: pane.height
        horizontalAlignment: Text.AlignHCenter
        text: screen.translate.tips.noSeries
        color: Theme.faint
    }
    ProblemEditor {
        id: editor
        objectName: "trEditor"
        visible: screen.editing
        y: parent.height - height
        width: parent.width
        translate: screen.translate
    }
    Message {
        id: undo
        objectName: "trUndo"
        visible: screen.deleted !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        y: pane.y + pane.height - height - 12 - (bar.visible ? 46 : 0)
        fact: [{ text: "Deleted ", kind: "" }, { text: screen.deleted, kind: "n" }]
        verbs: [{ text: "Undo", kind: "main", id: "undo" }]
        onVerbActivated: {
            screen.translate.undoPromptDelete()
            screen.deleted = ""
        }
    }
    BottomBar {
        id: bar
        objectName: "trBar"
        visible: screen.segments.length > 0 && !screen.editing
        anchors.horizontalCenter: parent.horizontalCenter
        y: pane.y + pane.height - height - 12
        segments: screen.segments
        sat: screen.translate.moreVisible
        satTip: screen.translate.tips.more
        onActivated: (i, id) => screen.translate.act(id)
        onSatClicked: screen.openMenu(moreMenu, screen.translate.moreItems(), bar.satItem)
    }
    Menu {
        id: moreMenu
        objectName: "trMoreMenu"
        onPicked: (i, id) => screen.translate.moreAct(id)
    }
    Menu {
        id: rowMenu
        objectName: "trRowMenu"
        property int rowIndex: -1
        onPicked: (i, id) => screen.translate.readRow(rowIndex)
    }
    PromptDrop {
        id: promptDrop
        objectName: "promptDrop"
        tipDelete: screen.translate.tips.promptDelete
        onPicked: id => screen.translate.choosePrompt(id)
        onDeleteRequested: id => screen.translate.deletePrompt(id)
    }
    TimePop {
        id: timePop
        objectName: "timePop"
        translate: screen.translate
    }
    Loader {
        id: langLoader
        active: false
        anchors.fill: parent
        sourceComponent: DropDown {
            objectName: "trLangDrop"
            filtering: true
            placeholder: "Find or type a language"
            cardWidth: 260
            onFilterChanged: text => entries = screen.translate.languageEntries(text)
            onPicked: (i, id) => screen.translate.chooseLanguage(id)
        }
    }
    Connections {
        target: screen.translate
        function onPromptDeleted(name) {
            screen.deleted = name
            hideUndo.restart()
        }
    }
    Timer {
        id: hideUndo
        interval: 9000
        onTriggered: screen.deleted = ""
    }
}
