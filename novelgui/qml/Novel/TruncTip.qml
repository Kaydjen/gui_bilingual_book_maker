pragma ComponentBehavior: Bound
import QtQuick

// A tooltip with the whole text of an elided Text, only while the text is cut. Put it inside the Text; `full` replaces the
// text when the shown text is only part of it.
TipArea {
    id: area

    property string full: ""
    readonly property Text label: parent as Text
    readonly property bool cut: label !== null && label.truncated

    tip: cut ? (full !== "" ? full : label.text) : ""
}
