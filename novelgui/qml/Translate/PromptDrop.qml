pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The prompt list under `Prompt ▾`: the saved prompts (the one in use marked), a `✕` on hover deletes one (not Default), and
// `+ New prompt` at the end opens the editor empty. entries: {id, text, current, deletable} as the view-model gives them.
Floating {
    id: drop

    property var entries: []
    property var tipDelete: ""
    signal picked(string id)
    signal deleteRequested(string id)

    cardWidth: 240

    Column {
        width: parent.width
        Repeater {
            model: drop.entries
            delegate: Item {
                id: item
                required property int index
                required property var modelData
                readonly property bool fresh: modelData.id === "+new"
                width: parent.width
                height: fresh ? 34 : 28

                Rectangle {
                    visible: item.fresh
                    x: 2
                    width: parent.width - 4
                    height: 1
                    color: Theme.divider
                }
                Rectangle {
                    visible: itemHover.hovered
                    y: item.fresh ? 5 : 0
                    width: parent.width
                    height: 28
                    radius: Theme.rRow
                    color: Theme.lift2
                }
                Rectangle {
                    visible: item.modelData.current === true
                    x: 4
                    y: 7
                    width: 2
                    height: 14
                    radius: 1
                    color: Theme.bright
                }
                AppText {
                    objectName: "promptItem" + item.index
                    x: 14
                    y: item.fresh ? 5 : 0
                    width: parent.width - 28 - (item.modelData.deletable === true ? 22 : 0)
                    height: 28
                    elide: Text.ElideRight
                    text: item.modelData.text
                    color: item.fresh ? (itemHover.hovered ? Theme.bright : Theme.dim)
                           : (item.modelData.current === true || itemHover.hovered ? Theme.bright : Theme.text)
                }
                HoverHandler { id: itemHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: { drop.close(); drop.picked(item.modelData.id) } }
                AppText {
                    objectName: "promptDelete" + item.index
                    visible: item.modelData.deletable === true
                    opacity: itemHover.hovered ? 1 : 0
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    width: 20
                    height: 28
                    horizontalAlignment: Text.AlignHCenter
                    font.family: Theme.symbolFamily
                    text: "✕"
                    color: xHover.hovered ? Theme.bright : Theme.dim
                    HoverHandler { id: xHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: { drop.close(); drop.deleteRequested(item.modelData.id) } }
                    TipArea { tip: drop.tipDelete }
                }
            }
        }
    }
}
