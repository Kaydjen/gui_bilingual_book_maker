import QtQuick
import Novel

// Every shared component in its states. `fake.ambient` names the one looping animation that runs ("wave", "spinner",
// "busy", "skeleton" or none); `fake.overlay` opens one overlay ("dropdown", "menu", "panel", "toast").
AppRoot {
    id: root

    readonly property string ambient: fake.ambient === undefined ? "" : fake.ambient
    readonly property bool bare: fake.bare === true
    readonly property string overlay: fake.overlay === undefined ? "" : fake.overlay

    Rectangle {
        anchors.fill: parent
        color: Theme.pane
    }

    Rectangle { visible: root.bare; anchors.fill: parent; color: Theme.pane; z: 650 }

    // ---- row 1: pills
    Row {
        x: 24
        y: 24
        spacing: 12
        Pill { objectName: "pillMain"; text: "Main pill"; kind: "main"; tip: "A main pill" }
        Pill { objectName: "pillNormal"; text: "Normal"; tip: ["Normal pill", [["Does", "nothing"], ["Next", "no"]]] }
        Pill { objectName: "pillFlat"; text: "Flat" ; kind: "flat" }
        Pill { objectName: "pillOff"; text: "Off"; kind: "off"; tip: "Why it is off" }
        Pill { objectName: "pillAccent"; text: "Accent"; kind: "accent" }
        Sat { objectName: "satLone"; tip: "More" }
    }

    // ---- row 2: top-row controls and segments
    Row {
        x: 24
        y: 74
        spacing: 12
        Ctl { objectName: "ctlNormal"; name: "To"; value: "Russian"; editText: "tag" }
        Ctl { objectName: "ctlRed"; name: "Key"; value: "Missing"; red: true }
        Ctl { objectName: "ctlOff"; name: "Prompt"; value: "Default"; off: true }
        Ctl { objectName: "ctlProgress"; name: "Check"; value: "40 %"; progress: 0.4 }
        Segmented { objectName: "segmented"; model: ["Terms", "Sample", "Check"]; currentIndex: 1 }
    }

    // ---- row 3: fields, lines, spinner, wave, text levels
    Row {
        x: 24
        y: 124
        spacing: 12
        Field { objectName: "fieldNormal"; value: "Knights"; width: 160 }
        Field { objectName: "fieldInvalid"; value: "Night Watch"; width: 160; keepOpen: true; Component.onCompleted: invalid = true }
        Field { objectName: "fieldEmpty"; value: ""; placeholder: "Search"; width: 140 }
        Item {
            width: 160
            height: 28
            BusyLine {
                objectName: "busyLine"
                y: 13
                width: parent.width
                trackColor: Theme.s3
                active: root.ambient === "busy"
            }
        }
        Item {
            width: 160
            height: 28
            BusyLine {
                objectName: "fillLine"
                y: 13
                width: parent.width
                value: 0.4
                trackColor: Theme.s3
            }
        }
        Spinner { objectName: "spinner"; y: 5; active: root.ambient === "spinner" }
        LetterWave { objectName: "wave"; y: 5; text: "Translate"; active: root.ambient === "wave" }
    }
    Row {
        x: 24
        y: 168
        spacing: 24
        AppText { objectName: "levelBright"; text: "HHHH bright"; color: Theme.bright; font.pixelSize: 16 }
        AppText { objectName: "levelText"; text: "HHHH normal"; color: Theme.text; font.pixelSize: 16 }
        AppText { objectName: "levelDim"; text: "HHHH dim"; color: Theme.dim; font.pixelSize: 16 }
        AppText { objectName: "levelFaint"; text: "HHHH faint"; color: Theme.faint; font.pixelSize: 16 }
        AppText { objectName: "symbols"; text: "▾ › ⋯ ✕ •••"; color: Theme.dim }
    }

    // ---- the table, with the skeleton beside it
    DataList {
        id: table
        objectName: "table"
        x: 24
        y: 210
        width: 560
        height: 200
        model: rowsModel
        cursorIndex: 2
        columnSet: ColumnSet {
            columns: [
                { key: "no", title: "No", width: 60 },
                { key: "title", title: "Chapter", flex: 1 },
                { key: "state", title: "State", width: 120, align: "right" }
            ]
        }
        onRowPressed: (i, ctrl, shift) => rec.record("rowPressed", [i, ctrl, shift])
        onRowDragged: i => rec.record("rowDragged", i)
        onMoveCursor: (d, ext) => rec.record("moveCursor", [d, ext])
        onToggleCurrent: rec.record("toggle", 1)
        onSelectAll: rec.record("selectAll", 1)
        onMoveTo: (w, ext) => rec.record("moveTo", [w, ext])
    }
    ListModel {
        id: rowsModel
        ListElement { no: "1"; title: "Chapter 1 - The Gate"; state: "translated"; selected: false; current: false }
        ListElement { no: "2"; title: "Chapter 2 - Percival"; state: "translated"; selected: true; current: false }
        ListElement { no: "3"; title: "Chapter 3 - Cornwall"; state: "translating"; selected: true; current: true }
        ListElement { no: "4"; title: "Chapter 4 - Low Tide"; state: "waiting"; selected: false; current: false }
        ListElement { no: "5"; title: "Chapter 5 - The Lake"; state: "waiting"; selected: false; current: false }
        ListElement { no: "6"; title: "Chapter 6 - Morgana"; state: "waiting"; selected: false; current: false }
        ListElement { no: "7"; title: "Chapter 7 - Silver Spear"; state: "waiting"; selected: false; current: false }
        ListElement { no: "8"; title: "Chapter 8 - Moon Gate"; state: "waiting"; selected: false; current: false }
    }
    Rectangle {
        x: 604
        y: 210
        width: 400
        height: 90
        radius: Theme.rPane
        color: Theme.pane
        Skeleton {
            objectName: "skeleton"
            anchors.fill: parent
            rows: 3
            cells: [0.1, 0.5, 0.2]
            visible: true
            active: root.ambient === "skeleton"
        }
    }
    Tip {
        objectName: "tipStatic"
        x: 604
        y: 330
        text: "Static tooltip bubble with a longer sentence that wraps."
        facts: [["Filled by", "the model"], ["You can edit", "yes"]]
    }

    // ---- bottom: message and bar
    Message {
        objectName: "message"
        x: 24
        y: 438
        width: 560
        fact: [{ text: "Imported ", kind: "" }, { text: "214", kind: "n" }, { text: " terms · ", kind: "" },
               { text: "3 to choose", kind: "red" }]
        verbs: [{ text: "Show imported", kind: "main", id: "show", tip: "Show only the imported terms" },
                { text: "Close", kind: "" }]
    }
    BottomBar {
        objectName: "bottomBar"
        x: 640
        y: 480
        sat: true
        satTip: "Job actions"
        segments: [{ text: "Add to queue", kind: "main", id: "queue" }, { text: "Start", kind: "" },
                   { text: "Sample", kind: "off", tip: "Nothing selected" }, { text: "Stop", kind: "accent" }]
    }
    Item {
        id: anchorBox
        objectName: "anchorBox"
        x: 24
        y: 610
        width: 120
        height: 30
        Pill { id: opener; text: "Opener ▾"; objectName: "opener" }
    }

    // ---- overlays (one at a time)
    DropDown {
        id: dd
        objectName: "dropdown"
        filtering: true
        entries: [
            { group: "Tuned" }, { text: "Russian", id: "ru", current: true, note: "ru" },
            { group: "Usable" }, { text: "Ukrainian", id: "uk", note: "uk" }, { text: "Polish", id: "pl", note: "pl" },
            { group: "Other" }, { text: "English", id: "en", off: true }
        ]
        onPicked: (i, id) => rec.record("dropdownPicked", id)
        onFilterChanged: t => rec.record("dropdownFilter", t)
    }
    Menu {
        id: menu
        objectName: "menu"
        items: [{ text: "Rename", id: "rename" }, { text: "Open folder", id: "folder" }, "-", "✓Sort by number", "~Remove book"]
        onPicked: (i, id) => rec.record("menuPicked", id)
    }
    Panel {
        id: panel
        objectName: "panel"
        title: "Remove book"
        actionText: "Remove"
        panelWidth: 440
        onAccepted: rec.record("panelAccepted", 1)
        onCloseRequested: rec.record("panelClosed", 1)
        AppText {
            width: parent.width
            wrapMode: Text.Wrap
            lineHeight: 1.4
            text: "Book 2 leaves the series. Its translated chapters and its job go to the trash."
            color: Theme.dim
        }
        Field { objectName: "panelField"; y: 70; width: parent.width; value: "Book 2"
            validate: t => t.length > 0 && t.length < 10; invalidTip: "1 to 9 characters"
            onCommitted: t => rec.record("fieldCommitted", t) }
    }
    Item { objectName: "liveProbe"; visible: false; property bool live: Visual.live }
    Toast {
        id: toast
        objectName: "toast"
    }
    Component.onCompleted: Qt.callLater(function () {
        if (overlay === "dropdown") dd.openUnder(opener)
        else if (overlay === "menu") menu.openAt(700, 540)
        else if (overlay === "panel") panel.open()
        else if (overlay === "toast") toast.show("Saved terms.json")
    })
}
