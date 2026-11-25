pragma ComponentBehavior: Bound
import QtQuick
import Novel
import Books

// The head of the term table (mock .thead): the head box (none -> all, some or all -> none), headings that sort, `To ▾` (red
// while no language is chosen, 3.4; else the language name, a click opens the same list), `Type ▾` (the heading is the filter:
// the chosen type replaces the word and stays bright), header splitters that resize a column.
Item {
    id: head

    property var terms: null
    property ColumnSet columns: null
    signal toClicked(Item anchorItem)
    signal typeClicked(Item anchorItem)

    height: Theme.rowHeight

    function title(c) {
        if (c.key === "ren")
            return terms.nolang ? "To ▾" : terms.languageName + " ▾"
        if (c.key === "typ")
            return (terms.typeFilter !== "" ? terms.typeFilter.charAt(0).toUpperCase() + terms.typeFilter.slice(1) : "Type") + " ▾"
        var on = terms.sortKey === c.sort
        return (on ? (terms.sortDesc ? "↓ " : "↑ ") : "") + c.title
    }
    function tone(c) {
        if (c.key === "ren" && terms.nolang)
            return Theme.accent
        if (c.key === "typ" && terms.typeFilter !== "")
            return Theme.bright
        return terms.sortKey === c.sort ? Theme.text : Theme.dim
    }
    function tipOf(c) {
        if (c.key === "ren")
            return terms.nolang ? terms.tips.toEmpty : "Rendering in " + terms.languageName + ". Double-click or Enter to edit."
        if (c.key === "typ")
            return terms.typeFilter !== "" ? "Only " + terms.typeFilter + ". Click: another type or all." : terms.tips.type
        return ""
    }
    function clicked(c, item) {
        if (c.key === "ren")
            toClicked(item)
        else if (c.key === "typ")
            typeClicked(item)
        else if (c.key !== "box")
            terms.sortBy(c.key)
    }

    Row {
        x: 8
        height: parent.height
        Repeater {
            model: head.columns.columns
            delegate: Item {
                id: cell
                required property var modelData
                width: head.columns.widthOf(modelData.key)
                height: head.height

                HeadBox {
                    visible: cell.modelData.key === "box"
                    objectName: "headBox"
                    x: (cell.width - width) / 2
                    anchors.verticalCenter: parent.verticalCenter
                    mode: head.terms.headState
                    onToggled: head.terms.headBox()
                }
                AppText {
                    id: label
                    objectName: "termHead_" + cell.modelData.key
                    visible: cell.modelData.key !== "box"
                    width: parent.width
                    height: parent.height
                    rightPadding: 8
                    elide: Text.ElideRight
                    text: head.title(cell.modelData)
                    color: head.tone(cell.modelData)
                    horizontalAlignment: cell.modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                    HoverHandler { id: labelHover; enabled: label.visible; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: head.clicked(cell.modelData, label) }
                    TipArea { tip: head.tipOf(cell.modelData) }
                }
                Item {
                    id: splitter
                    objectName: "splitter_" + cell.modelData.key
                    visible: cell.modelData.fixed !== true
                    x: parent.width - 4
                    width: 8
                    height: parent.height
                    property real base: 0
                    HoverHandler { id: splitHover; cursorShape: Qt.SizeHorCursor }
                    Rectangle {
                        visible: splitHover.hovered || drag.active
                        x: 3
                        y: 6
                        width: 1
                        height: parent.height - 12
                        color: Theme.s4
                    }
                    DragHandler {
                        id: drag
                        target: null
                        yAxis.enabled: false
                        onActiveChanged: if (active) splitter.base = cell.width
                        onTranslationChanged: if (active) head.columns.resize(cell.modelData.key, splitter.base + translation.x)
                    }
                }
            }
        }
    }
    Rectangle {
        anchors.bottom: parent.bottom
        x: 6
        width: parent.width - 12
        height: 1
        color: Theme.rowLine
    }
}
