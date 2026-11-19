import QtQuick

// The head box of the chapter table: `none`, `some` (a dash) or `all`; a click toggles through the view-model.
Item {
    id: head

    property string mode: "none"
    signal toggled()

    width: 16
    height: 16

    CheckMark {
        checked: head.mode === "all"
        dash: head.mode === "some"
        hot: hover.hovered
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: head.toggled() }
}
