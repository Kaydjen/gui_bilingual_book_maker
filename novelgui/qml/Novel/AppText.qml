pragma ComponentBehavior: Bound
import QtQuick

// Text with the fixed render type and the font fallback of the window (Segoe UI, a system UI font;
// the symbols of the controls come from the system symbol fallback).
Text {
    color: Theme.text
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSize
    renderType: Text.QtRendering
    textFormat: Text.PlainText
    elide: Text.ElideNone
    verticalAlignment: Text.AlignVCenter
}
