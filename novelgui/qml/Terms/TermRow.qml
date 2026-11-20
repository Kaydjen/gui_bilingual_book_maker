pragma ComponentBehavior: Bound
import QtQuick
import Novel
import Books

// A term row (mock .tr): box, source, rendering, type, gender, First, Count, About. The roles come from the TermModel (7 strings
// made once on the data lane). A rendering is a field in place (double-click / Enter), a choice (chips), an empty slot for a mined
// name (type it + Enter), or a dim dash while no language is chosen. Type and Gender open their list at once.
RowBase {
    id: row

    property var terms: null
    property ColumnSet columns: null
    property real shimmer: 1
    signal pickType(Item anchorItem, int index)
    signal pickGender(Item anchorItem, int index)
    required property string src
    required property string ren
    required property string typ
    required property string gen
    required property string fc
    required property string about
    required property string flags
    required property var model
    readonly property var parts: fc.split("\x1f")
    readonly property bool suggestion: flags.indexOf("s") >= 0
    readonly property bool nolang: flags.indexOf("n") >= 0
    readonly property bool renChoice: flags.indexOf("r") >= 0
    readonly property bool genChoice: flags.indexOf("g") >= 0
    readonly property bool editRen: terms.editRow === rowIndex && terms.editField === "ren"
    readonly property bool editAbout: terms.editRow === rowIndex && terms.editField === "about"
    readonly property bool unscanned: terms.scanning && parts[0] === ""

    selected: model.selected === true
    current: model.current === true

    Item {
        width: row.columns.widthOf("box")
        height: Theme.rowHeight
        CheckMark {
            anchors.centerIn: parent
            checked: row.selected
            hot: row.hovered
        }
        MouseArea {
            objectName: "box_" + row.rowIndex
            anchors.fill: parent
            onPressed: row.terms.rowPressed(row.rowIndex, true, false, false)
        }
    }
    AppText {
        objectName: "termSrc_" + row.rowIndex
        width: row.columns.widthOf("src")
        height: Theme.rowHeight
        rightPadding: 8
        elide: Text.ElideRight
        text: row.src
        color: row.selected || row.current ? Theme.bright : Theme.text
    }
    Item {
        id: renCell
        width: row.columns.widthOf("ren")
        height: Theme.rowHeight
        clip: !row.editRen

        AppText {
            objectName: "termRen_" + row.rowIndex
            visible: !row.editRen && !row.suggestion && (!row.renChoice || row.nolang)
            width: parent.width
            height: parent.height
            rightPadding: 8
            elide: Text.ElideRight
            text: row.nolang ? "—" : row.ren
            color: row.nolang ? Theme.faint : Theme.bright
        }
        Loader {
            active: row.renChoice && !row.editRen && !row.nolang
            width: parent.width - 8
            height: parent.height
            sourceComponent: ChipCell {
                objectName: "termChips_" + row.rowIndex
                values: row.ren.split("")
                raised: row.selected || row.current
                terms: row.terms
                rowIndex: row.rowIndex
                field: "ren"
                onTypeAnother: row.terms.beginEdit(row.rowIndex, "ren")
            }
        }
        Loader {
            active: row.suggestion && !row.nolang
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(150, parent.width - 8)
            height: 22
            sourceComponent: Inset {
                objectName: "termSlot_" + row.rowIndex
                edge: slot.activeFocus ? Theme.fieldFocus : Theme.fieldLine
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.IBeamCursor
                    onPressed: slot.forceActiveFocus()
                }
                TextInput {
                    id: slot
                    property bool settled: false
                    x: 6
                    width: parent.width - 12
                    height: parent.height
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.bright
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize
                    clip: true
                    function give() {
                        if (settled)
                            return
                        settled = true
                        row.terms.nameRendering(row.rowIndex, text)
                    }
                    onAccepted: give()
                    onActiveFocusChanged: if (!activeFocus) give()          // a click away or Tab names it, as a field commits
                    Keys.onEscapePressed: {
                        settled = true
                        text = ""
                        focus = false
                    }
                }
                TipArea { tip: row.terms.tips.slot }
            }
        }
        AppText {
            visible: row.suggestion && row.nolang
            width: parent.width
            height: parent.height
            text: "—"
            color: Theme.faint
        }
        Loader {
            active: row.editRen
            x: -4
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 24
            sourceComponent: CellEdit {
                objectName: "editRen_" + row.rowIndex
                value: row.renChoice ? row.ren.split("\x1f")[0] : row.ren
                onTaken: text => row.terms.commitCell(text)
                onTabbed: row.terms.nextCell()
                onFinished: row.terms.endEdit()
            }
        }
    }
    Item {
        id: typCell
        width: row.columns.widthOf("typ")
        height: Theme.rowHeight
        Rectangle {
            visible: typHover.containsMouse
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 10
            height: 22
            radius: 5
            color: Theme.lift2
        }
        AppText {
            objectName: "termType_" + row.rowIndex
            width: parent.width
            height: parent.height
            leftPadding: 4
            elide: Text.ElideRight
            text: row.typ === "" ? "—" : row.typ
            color: typHover.containsMouse ? Theme.bright : (row.typ === "" ? Theme.faint : Theme.dim)
        }
        MouseArea {
            id: typHover
            anchors.fill: parent
            enabled: !row.suggestion
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.pickType(typCell, row.rowIndex)
        }
    }
    Item {
        id: genCell
        width: row.columns.widthOf("gen")
        height: Theme.rowHeight
        Rectangle {
            visible: genHover.containsMouse
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 8
            height: 22
            radius: 5
            color: Theme.lift2
        }
        AppText {
            objectName: "termGender_" + row.rowIndex
            visible: !row.genChoice
            width: parent.width
            height: parent.height
            leftPadding: 4
            text: row.gen === "" ? "—" : row.gen
            color: genHover.containsMouse ? Theme.bright : (row.gen === "" ? Theme.faint : Theme.dim)
        }
        Loader {
            active: row.genChoice
            height: parent.height
            width: parent.width
            sourceComponent: ChipCell {
                objectName: "genderChips_" + row.rowIndex
                values: row.gen.split("")
                raised: row.selected || row.current
                terms: row.terms
                rowIndex: row.rowIndex
                field: "gender"
            }
        }
        MouseArea {
            id: genHover
            anchors.fill: parent
            enabled: !row.suggestion && !row.genChoice
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.pickGender(genCell, row.rowIndex)
        }
    }
    Item {
        width: row.columns.widthOf("first")
        height: Theme.rowHeight
        AppText {
            objectName: "termFirst_" + row.rowIndex
            visible: !row.unscanned
            width: parent.width
            height: parent.height
            rightPadding: 14
            horizontalAlignment: Text.AlignRight
            text: row.parts[0]
            color: Theme.dim
        }
        Rectangle {
            visible: row.unscanned
            x: parent.width - 14 - width
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 8
            radius: 2
            color: Theme.s3
            opacity: row.shimmer
        }
    }
    Item {
        width: row.columns.widthOf("count")
        height: Theme.rowHeight
        AppText {
            objectName: "termCount_" + row.rowIndex
            visible: !row.unscanned
            width: parent.width
            height: parent.height
            rightPadding: 16
            horizontalAlignment: Text.AlignRight
            text: row.parts[1]
            color: Theme.dim
        }
        Rectangle {
            visible: row.unscanned
            x: parent.width - 16 - width
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 8
            radius: 2
            color: Theme.s3
            opacity: row.shimmer
        }
    }
    Item {
        width: row.columns.widthOf("about")
        height: Theme.rowHeight
        clip: !row.editAbout

        AppText {
            objectName: "termAbout_" + row.rowIndex
            visible: !row.editAbout
            width: parent.width
            height: parent.height
            rightPadding: 8
            elide: Text.ElideRight
            text: row.about === "" ? "—" : row.about
            color: row.about === "" ? Theme.faint : Theme.dim
        }
        MouseArea {
            anchors.fill: parent
            enabled: !row.editAbout
            onDoubleClicked: row.terms.beginEdit(row.rowIndex, "about")
        }
        Loader {
            active: row.about === ""
            anchors.fill: parent
            sourceComponent: TipArea { tip: row.terms.tips.unknown }
        }
        Loader {
            active: row.editAbout
            x: -4
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 24
            sourceComponent: CellEdit {
                objectName: "editAbout_" + row.rowIndex
                value: row.about
                onTaken: text => row.terms.commitCell(text)
                onFinished: row.terms.endEdit()
            }
        }
    }
}
