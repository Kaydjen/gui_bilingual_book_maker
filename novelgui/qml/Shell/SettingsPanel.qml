pragma ComponentBehavior: Bound
import QtQuick
import Novel

// Settings v4 (window_spec 11.7): KEYS and MODELS with `+` at the heading's right end, the TRANSLATION rows as sentences
// (control first), the LIBRARY, APP DATA and GRAPHICS rows and the flat `Log` button at the end of the scrolled content.
// Every change saves at once, the changed row glows once and the dim saved line shows at the top centre of the card
// (owner 2026-11-19: seen while the settings scroll; nothing shifts).
FocusScope {
    id: panel

    property var app: null
    property var vm: null
    property bool addingKey: false
    property bool editingPace: false
    readonly property real innerWidth: card.width - 44

    anchors.fill: parent
    visible: app !== null && app.settingsOpen
    z: 600

    function close() {
        app.closeSettings()
    }
    function glowRow(name) {
        var rows = { "keys": keysBox, "models": modelsBox, "pace": paceRow, "awake": awakeRow, "graphics": graphicsRow }
        var t = rows[name]
        if (!t)
            return
        var p = t.mapToItem(scroll.contentItem, 0, 0)
        glowRect.x = p.x - 4
        glowRect.y = p.y - 3
        glowRect.width = t.width + 8
        glowRect.height = t.height + 6
        flash.restart()
    }
    onVisibleChanged: {
        if (visible) {
            forceActiveFocus()
            vm.measureAppData()
            vm.refreshStates()
        } else {
            addingKey = false
        }
    }
    Connections {
        target: panel.vm
        function onGlow(name) {
            panel.glowRow(name)
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.veil
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onPressed: {
                card.forceActiveFocus()
                panel.close()
            }
        }
    }
    Surface {
        id: card
        objectName: "settingsCard"
        anchors.centerIn: parent
        width: Math.min(540, panel.width - 40)
        height: Math.min(panel.height - 40, 20 + content.height + 16)
        level: 3
        radius: Theme.rPanel
        color: Theme.panel
        MouseArea { anchors.fill: parent }

        Item {
            id: closeBtn
            objectName: "settingsClose"
            x: parent.width - 36
            y: 10
            width: 26
            height: 26
            z: 3
            AppText {
                anchors.centerIn: parent
                text: "✕"
                font.pixelSize: 14
                color: closeHover.hovered ? Theme.bright : Theme.dim
            }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: panel.close() }
            TipArea { tip: "Close (Esc)" }
        }
        ScrollAssist {
            flickable: scroll
        }
        Item {
            x: scroll.x
            y: scroll.y
            z: 1
            width: scroll.width
            height: scroll.height
            Fades {
                flickable: scroll
                color: Theme.panel
                bottomHeight: 40
                topHeight: 24
            }
        }
        Flickable {
            id: scroll
            x: 22
            y: 20
            width: panel.innerWidth
            height: parent.height - 20 - 16
            contentHeight: content.height
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: content
                width: scroll.width
                spacing: 6

                Item { width: 1; height: 14 }
                SectionHead {
                    objectName: "headKeys"
                    width: parent.width
                    text: "KEYS"
                    plus: true
                    tip: panel.app.tips.keysHead
                    plusTip: panel.app.tips.keysPlus
                    onPlusClicked: {
                        panel.addingKey = true
                        keyInput.input.forceActiveFocus()
                    }
                }
                Rectangle {
                    id: keysBox
                    objectName: "keysBox"
                    width: parent.width
                    height: keyList.count * 30 + (panel.addingKey ? 30 : 0) + 6
                    radius: 8
                    color: Theme.pane
                    ListView {
                        id: keyList
                        objectName: "keyList"
                        x: 0
                        y: 3
                        width: parent.width
                        height: count * 30
                        interactive: false
                        model: panel.vm.keys
                        delegate: KeyRow {
                            onRemoveClicked: panel.vm.removeKey(index)
                        }
                    }
                    Field {
                        id: keyInput
                        objectName: "keyInput"
                        visible: panel.addingKey
                        x: 6
                        y: keyList.count * 30 + 4
                        width: parent.width - 12
                        height: 28
                        placeholder: "Paste a key"
                        onCommitted: text => {
                            panel.vm.addKeys(text)
                            panel.addingKey = false
                        }
                        onEditingChanged: if (!editing) panel.addingKey = false
                    }
                }

                Item { width: 1; height: 10 }
                SectionHead {
                    id: modelsHead
                    objectName: "headModels"
                    width: parent.width
                    text: "MODELS"
                    plus: true
                    tip: panel.app.tips.modelsHead
                    plusTip: "Add a model"
                    onPlusClicked: {
                        panel.vm.loadGoogle()
                        modelDd.entries = panel.vm.modelEntries("")
                        var p = modelsHead.mapToItem(modelDd, modelsHead.width - modelDd.cardWidth, modelsHead.height + 4)
                        modelDd.openAt(p.x, p.y)
                    }
                }
                Rectangle {
                    id: modelsBox
                    objectName: "modelsBox"
                    width: parent.width
                    height: modelList.count * 30 + 6
                    radius: 8
                    color: Theme.pane
                    ListView {
                        id: modelList
                        objectName: "modelList"
                        y: 3
                        width: parent.width
                        height: count * 30
                        interactive: false
                        model: panel.vm.modelRows
                        delegate: ModelRow {
                            onMoveClicked: delta => panel.vm.moveModel(index, delta)
                            onRemoveClicked: panel.vm.removeModel(index)
                            onRenamed: text => panel.vm.renameModel(index, text)
                        }
                    }
                }

                Item { width: 1; height: 10 }
                SectionHead { width: parent.width; text: "TRANSLATION" }
                Row {
                    id: paceRow
                    objectName: "paceRow"
                    height: 34
                    spacing: 10
                    Item {
                        width: 46
                        height: 30
                        y: 2
                        Surface {
                            anchors.fill: parent
                            visible: !panel.editingPace
                            level: 1
                            color: Theme.pill
                            AppText {
                                objectName: "paceValue"
                                anchors.centerIn: parent
                                text: panel.vm.pace
                                color: Theme.bright
                            }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                onTapped: {
                                    panel.editingPace = true
                                    paceField.input.forceActiveFocus()
                                }
                            }
                        }
                        Field {
                            id: paceField
                            objectName: "paceField"
                            visible: panel.editingPace
                            anchors.fill: parent
                            value: panel.vm.pace
                            keepOpen: true
                            validate: t => panel.vm.setPace(t)
                            invalidTip: "1 to 120"
                            onEditingChanged: {
                                if (!editing) {
                                    input.text = panel.vm.pace
                                    invalid = false
                                    panel.editingPace = false
                                }
                            }
                            onCommitted: panel.editingPace = false
                        }
                    }
                    AppText {
                        height: 34
                        text: "requests a minute"
                        color: Theme.text
                        TipArea { tip: panel.app.tips.paceRow }
                    }
                    AppText {
                        objectName: "paceUnit"
                        height: 34
                        text: "· " + (panel.editingPace ? panel.vm.unitFor(paceField.input.text) : panel.vm.paceUnit)
                        color: Theme.dim
                    }
                }
                Row {
                    id: awakeRow
                    objectName: "awakeRow"
                    height: 34
                    spacing: 10
                    Item {
                        width: 46
                        height: 34
                        Switch {
                            objectName: "awakeSwitch"
                            anchors.verticalCenter: parent.verticalCenter
                            checked: panel.vm.keepAwake
                            off: !panel.vm.awakeAvailable
                            onToggled: value => panel.vm.setKeepAwake(value)
                        }
                    }
                    AppText {
                        objectName: "awakeLabel"
                        height: 34
                        text: "Keep the computer awake while translating"
                        color: panel.vm.awakeAvailable ? Theme.text : Theme.faint
                        TapHandler { onTapped: panel.vm.setKeepAwake(!panel.vm.keepAwake) }
                        TipArea { tip: panel.vm.awakeTip }
                    }
                }

                Item { width: 1; height: 10 }
                SectionHead { width: parent.width; text: "LIBRARY" }
                Seg2 {
                    objectName: "libraryRow"
                    name: panel.vm.libraryName
                    action: "Change…"
                    actionOff: panel.vm.running
                    nameTip: panel.vm.libraryTip
                    actionTip: panel.vm.changeTip
                    onNameClicked: panel.vm.openLibrary()
                    onActionClicked: panel.vm.changeLibrary()
                }
                Item { width: 1; height: 4 }
                SectionHead { width: parent.width; text: "APP DATA" }
                Seg2 {
                    objectName: "appDataRow"
                    name: "App data" + (panel.vm.appDataText !== "" ? " · " + panel.vm.appDataText : "")
                    action: "Open folder"
                    nameTip: panel.app.tips.appData
                    actionTip: "Open the folder"
                    onNameClicked: panel.vm.openAppData()
                    onActionClicked: panel.vm.openAppData()
                }
                Item { width: 1; height: 4 }
                SectionHead { width: parent.width; text: "GRAPHICS" }
                Item {
                    id: graphicsRow
                    objectName: "graphicsRow"
                    width: parent.width
                    height: 34
                    Segmented {
                        objectName: "graphicsSeg"
                        model: [{ "text": "Auto" }, { "text": "Software", "tip": panel.app.tips.graphics }]
                        currentIndex: panel.vm.graphics === "software" ? 1 : 0
                        onActivated: index => panel.vm.setGraphics(index === 1 ? "software" : "auto")
                    }
                }
                Item { width: 1; height: 10 }
                Pill {
                    objectName: "settingsLog"
                    kind: "flat"
                    text: "Log"
                    tip: panel.app.tips.logButton
                    onClicked: panel.app.openLog()
                }
                Item { width: 1; height: 4 }
            }
            Rectangle {
                id: glowRect
                parent: scroll.contentItem       // not inside the Column: a positioned child would take a slot
                z: -1
                visible: opacity > 0
                opacity: 0
                radius: 8
                color: Qt.rgba(1, 1, 1, 0.07)
                SequentialAnimation {
                    id: flash
                    NumberAnimation { target: glowRect; property: "opacity"; from: 0; to: 1; duration: 120 }
                    NumberAnimation { target: glowRect; property: "opacity"; to: 0; duration: 800 }
                }
            }
        }
        AppText {
            objectName: "savedLine"
            x: 44
            y: 10
            z: 3
            width: parent.width - 88
            height: 26
            horizontalAlignment: Text.AlignHCenter
            text: panel.vm.saved
            color: Theme.dim
            font.pixelSize: 12
            elide: Text.ElideRight
            opacity: panel.vm.saved !== "" ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 250 } }
        }
    }
    DropDown {
        id: modelDd
        objectName: "modelDd"
        z: 10
        filtering: true
        placeholder: "Find or type a model"
        cardWidth: 300
        onFilterChanged: text => {
            entries = panel.vm.modelEntries(text)
            if (entries.length > 0 && entries[0].add === true)
                hot = 0
        }
        onPicked: (index, id) => panel.vm.addModel(id)
    }
    Connections {
        target: panel.vm
        function onGoogleChanged() {
            if (modelDd.visible)
                modelDd.entries = panel.vm.modelEntries(modelDd.filterText)
        }
    }
    Keys.onEscapePressed: close()
}
