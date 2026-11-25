pragma ComponentBehavior: Bound
import QtQuick

// A text cell of a row: takes its width from the shared ColumnSet by column key.
AppText {
    property var columns: null
    property string column: ""
    property string align: "left"

    width: columns ? columns.widthOf(column) : 100
    height: parent ? parent.height : implicitHeight
    elide: Text.ElideRight
    horizontalAlignment: align === "right" ? Text.AlignRight : (align === "center" ? Text.AlignHCenter : Text.AlignLeft)
    rightPadding: 8
}
