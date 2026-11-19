pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The top row of Translate (7.16): `To` first, the reserved `From`, the split pill `Prompt Default ▾ | ✎`, `Sample`; at the
// right the `Time` pill. Every control is a filled pill with its name inside; the states and tooltips come from the TranslateVM.
Item {
    id: row

    property var translate: null
    readonly property var t: translate.top
    readonly property var time: translate.time
    property alias timeCtl: timePill
    signal toClicked(Item anchor)
    signal promptClicked(Item anchor)
    signal timeClicked(Item anchor)

    Row {
        x: 0
        y: 8
        spacing: 8
        Ctl {
            id: toPill
            objectName: "trTo"
            name: "To"
            value: row.t.toText || ""
            red: row.t.toRed === true
            off: row.t.toEnabled !== true
            tip: row.t.toTip || ""
            onClicked: row.toClicked(toPill)
        }
        Ctl {
            objectName: "trFrom"
            visible: (row.t.fromText || "") !== ""
            value: row.t.fromText || ""
            arrow: false
            off: true
            tip: row.t.fromTip || ""
        }
        Ctl {
            id: promptPill
            objectName: "trPrompt"
            name: "Prompt"
            value: row.t.promptName || ""
            editText: "✎"
            off: row.t.promptEnabled !== true
            tip: row.t.promptTip || ""
            editTip: row.t.editTip || ""
            onClicked: row.promptClicked(promptPill)
            onEditClicked: row.translate.promptEdit(false)
        }
        Ctl {
            objectName: "trSample"
            value: row.t.sampleText || "Sample"
            arrow: false
            off: row.t.sampleEnabled !== true
            progress: row.t.sampling === true ? row.t.samplePercent : -1
            tip: row.t.sampleTip || ""
            onClicked: row.translate.sample()
        }
    }
    Ctl {
        id: timePill
        objectName: "trTime"
        visible: row.time.visible === true
        anchors.right: parent.right
        y: 8
        name: "Time"
        value: row.time.text || ""
        bright: row.time.late !== true
        off: row.t.has !== true
        tip: row.time.tip || ""
        onClicked: row.timeClicked(timePill)
    }
}
