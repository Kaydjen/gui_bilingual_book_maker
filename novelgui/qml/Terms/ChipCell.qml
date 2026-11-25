pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The values of an open choice side by side (F5, 6.7): `Персиваль | Парсифаль`, gender `м | ж`. A click takes one (the field is
// locked and the row ticked), a double-click types another value. Hover says where the candidate comes from.
Row {
    id: chips

    property var values: []
    property var terms: null
    property int rowIndex: -1
    property string field: "ren"
    signal typeAnother()

    spacing: 2
    Repeater {
        model: chips.values
        delegate: Row {
            id: unit
            required property int index
            required property string modelData
            spacing: 2
            height: chips.height

            AppText {
                visible: unit.index > 0
                height: parent.height
                text: "|"
                color: Theme.faint
            }
            Surface {
                objectName: "chip_" + chips.field + "_" + chips.rowIndex + "_" + unit.index
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(label.implicitWidth + 12, Math.max(24, (chips.width - 14 * chips.values.length) / chips.values.length))
                height: 22
                level: 1
                radius: 5
                color: chipHover.hovered ? Theme.lift2 : Theme.lift

                AppText {
                    id: label
                    x: 6
                    width: parent.width - 12
                    height: parent.height
                    elide: Text.ElideRight
                    text: unit.modelData
                    color: Theme.bright
                }
                HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: chips.terms.takeChip(chips.rowIndex, chips.field, unit.index)
                    onDoubleTapped: chips.typeAnother()
                }
                TipArea { tip: chips.terms.chipTip(chips.rowIndex, chips.field, unit.index) }
            }
        }
    }
}
