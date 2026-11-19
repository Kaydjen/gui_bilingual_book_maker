pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The Terms screen (6.7, 9.12): tabs on the left, search and `•••` on the right, the table (ListView + ColumnSet, probe d), the
// reader under it while one term is selected, and ONE element floating at the bottom of the table: the fact line and its verb,
// the bar of the ticked rows, `Reading the book · 40 %`, or a message of the last action. Everything comes from the TermsVM.
Item {
    id: screen

    property var terms: null
    property var app: null
    readonly property var spec: terms.floating
    readonly property bool narrow: width < 900
    property real shimmerPhase: 1

    function openDrop(anchorItem) {
        langLoader.active = true
        var drop = langLoader.item as DropDown
        drop.entries = terms.languageEntries("")
        drop.openUnder(anchorItem)
    }
    function openMenu(menu, items, anchorItem) {
        menu.items = items
        menu.openUnder(anchorItem)
    }
    function typeKey(event) {
        var printable = event.text.length === 1 && event.text > " " && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier))
        if (printable)
            search.focusField(event.text)
        return printable
    }

    // the toolbar: tabs left; right `⌕` and `•••`
    Item {
        id: bar
        objectName: "termsBar"
        width: parent.width
        height: 40

        TermTabs {
            id: tabs
            objectName: "termTabs"
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            terms: screen.terms
        }
        Surface {
            objectName: "importedChip"
            visible: screen.terms.importedCount > 0
            x: tabs.x + tabs.width + 10
            anchors.verticalCenter: parent.verticalCenter
            width: chipLabel.implicitWidth + 40
            height: 24
            level: 1
            radius: 12
            AppText {
                id: chipLabel
                x: 10
                height: parent.height
                text: "Imported"
                color: Theme.bright
            }
            AppText {
                objectName: "importedClear"
                anchors.right: parent.right
                anchors.rightMargin: 8
                height: parent.height
                text: "✕"
                font.family: Theme.symbolFamily
                color: chipHover.hovered ? Theme.bright : Theme.dim
                HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: screen.terms.clearImported() }
                TipArea { tip: "Only the " + screen.terms.importedCount + " terms of the last import. ✕ or Esc: all terms." }
            }
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            SearchBox {
                id: search
                objectName: "termSearch"
                terms: screen.terms
            }
            Item {
                id: more
                objectName: "termsMore"
                width: 32
                height: 30
                AppText {
                    anchors.centerIn: parent
                    text: "•••"
                    font.pixelSize: Theme.fontSize
                    font.weight: Font.Bold
                    font.letterSpacing: -1
                    color: screen.terms.importing ? Theme.faint : (moreHover.hovered ? Theme.bright : Theme.dim)
                }
                HoverHandler { id: moreHover; cursorShape: screen.terms.importing ? Qt.ArrowCursor : Qt.PointingHandCursor }
                TapHandler {
                    enabled: !screen.terms.importing
                    onTapped: screen.openMenu(moreMenu, screen.terms.moreItems(), more)
                }
                TipArea { tip: screen.terms.importing ? screen.terms.tips.moreBusy : screen.terms.tips.more }
            }
        }
    }

    Item {
        id: body
        y: bar.height
        width: parent.width
        height: parent.height - bar.height - (reader.visible ? reader.height : 0)

        Rectangle {
            anchors.fill: parent
            radius: Theme.rPane
            color: Theme.s1
        }
        TermHead {
            id: head
            objectName: "termHead"
            width: parent.width
            terms: screen.terms
            columns: cols
            onToClicked: item => screen.openDrop(item)
            onTypeClicked: item => screen.openMenu(filterMenu, screen.terms.typeFilterItems(), item)
        }
        DataList {
            id: grid
            objectName: "termTable"
            y: head.height
            width: parent.width
            height: parent.height - head.height
            header: false
            model: screen.terms.table
            cursorIndex: screen.terms.cursor
            columnSet: cols
            focus: true
            onRowPressed: (i, ctrl, shift) => screen.terms.rowPressed(i, false, ctrl, shift)
            onMoveCursor: (d, ext) => screen.terms.moveCursor(d, ext)
            onMoveTo: (w, ext) => screen.terms.moveTo(w, ext)
            onSelectAll: screen.terms.selectAll()
            onToggleCurrent: screen.terms.toggleCurrent()
            onRowActivated: i => screen.terms.activate(i)
            onCopyRequested: screen.terms.copyCursor()
            onDeleteRequested: screen.terms.floatVerb("delete")
            delegate: TermRow {
                id: item
                required property int index
                terms: screen.terms
                columns: cols
                rowIndex: item.index
                shimmer: screen.shimmerPhase
                onPickType: (anchorItem, i) => {
                    typeMenu.rowIndex = i
                    screen.openMenu(typeMenu, screen.terms.typeItems(i), anchorItem)
                }
                onPickGender: (anchorItem, i) => {
                    genderMenu.rowIndex = i
                    screen.openMenu(genderMenu, screen.terms.genderItems(i), anchorItem)
                }
            }
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape)
                    screen.terms.escape()
                event.accepted = event.key === Qt.Key_Escape || screen.typeKey(event)
            }
            Component.onCompleted: {
                list.objectName = "termList"
                list.bottomMargin = 84
            }
        }
        Skeleton {
            objectName: "termSkeleton"
            visible: screen.terms.skeleton
            y: head.height + 4
            x: 6
            width: parent.width - 12
            rows: Math.max(3, Math.floor((parent.height - head.height) / Theme.rowHeight) - 1)
            cells: [0.04, 0.28, 0.28]
            maskColor: Theme.s1
        }
        Column {
            objectName: "termsEmpty"
            visible: screen.terms.view === "empty"
            anchors.centerIn: parent
            spacing: 10
            Pill {
                objectName: "importEmpty"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Import"
                kind: screen.terms.nolang ? "off" : ""
                tip: screen.terms.nolang ? screen.terms.tips.noLang : screen.terms.tips.emptyImport
                onClicked: screen.terms.openImportDialog()
            }
            AppText {
                objectName: "termsEmptyText"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "No terms yet"
                color: Theme.dim
            }
        }
        // the one element at the bottom of the table
        Message {
            id: fact
            objectName: "termFloat"
            visible: screen.spec.kind !== "" && screen.spec.kind !== "ticked" && (screen.spec.fact || []).length > 0
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            fact: screen.spec.fact || []
            verbs: screen.spec.verbs || []
            progress: screen.spec.progress === undefined ? -1 : screen.spec.progress
            onVerbActivated: (i, id) => screen.terms.floatVerb(id)
            TipArea { tip: screen.spec.tip || "" }
        }
        BottomBar {
            objectName: "termBar"
            visible: (screen.spec.kind === "ticked" || screen.spec.kind === "confirm") && (screen.spec.fact || []).length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            segments: screen.spec.verbs || []
            onActivated: (i, id) => screen.terms.floatVerb(id)
        }
    }
    ReaderPane {
        id: reader
        objectName: "termReader"
        visible: screen.terms.reader.open === true
        y: parent.height - height
        width: parent.width
        height: Math.min(wanted + 10, screen.height - bar.height - 150)
        terms: screen.terms
        wanted: screen.narrow ? 150 : 200
    }
    ColumnSet {
        id: cols
        columns: [{ key: "box", title: "", width: 34, fixed: true },
                  { key: "src", title: "Source", sort: "source", flex: 1.2, min: 110 },
                  { key: "ren", title: "To", sort: "tr", flex: 1.2, min: 110 },
                  { key: "typ", title: "Type", sort: "type", width: screen.narrow ? 90 : 100, min: 60 },
                  { key: "gen", title: "Gender", sort: "gender", width: screen.narrow ? 54 : 70, min: 44 },
                  { key: "first", title: "First", sort: "first", width: screen.narrow ? 54 : 70, align: "right", min: 44 },
                  { key: "count", title: "Count", sort: "count", width: screen.narrow ? 56 : 72, align: "right", min: 44 },
                  { key: "about", title: "About", sort: "note", flex: 1, min: 90 }]
    }
    Menu {
        id: typeMenu
        objectName: "typeMenu"
        property int rowIndex: -1
        onPicked: (i, id) => screen.terms.pickCell(rowIndex, "type", id)
    }
    Menu {
        id: filterMenu
        objectName: "filterMenu"
        onPicked: (i, id) => screen.terms.pickTypeFilter(id)
    }
    Menu {
        id: genderMenu
        objectName: "genderMenu"
        property int rowIndex: -1
        onPicked: (i, id) => screen.terms.pickCell(rowIndex, "gender", id)
    }
    Menu {
        id: moreMenu
        objectName: "moreMenu"
        onPicked: (i, id) => screen.terms.morePicked(id)
    }
    Loader {
        id: langLoader
        active: false
        anchors.fill: parent
        sourceComponent: DropDown {
            objectName: "langDrop"
            filtering: true
            placeholder: "Find or type a language"
            cardWidth: 260
            onFilterChanged: text => entries = screen.terms.languageEntries(text)
            onPicked: (i, id) => screen.terms.chooseLanguage(id)
        }
    }
    SequentialAnimation {
        running: Visual.live && screen.terms.scanning && screen.terms.count > 0
        loops: Animation.Infinite
        NumberAnimation { target: screen; property: "shimmerPhase"; from: 1; to: 0.35; duration: 700 }
        NumberAnimation { target: screen; property: "shimmerPhase"; from: 0.35; to: 1; duration: 700 }
    }
    Shortcut {
        sequences: ["Alt+Left"]
        enabled: screen.visible && screen.terms.reader.open === true
        onActivated: screen.terms.stepPlace(-1)
    }
    Shortcut {
        sequences: ["Alt+Right"]
        enabled: screen.visible && screen.terms.reader.open === true
        onActivated: screen.terms.stepPlace(1)
    }
    Shortcut {
        sequences: ["Ctrl+F"]
        enabled: screen.visible
        onActivated: search.focusField("")
    }
}
