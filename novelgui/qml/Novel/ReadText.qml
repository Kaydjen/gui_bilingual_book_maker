pragma ComponentBehavior: Bound
import QtQuick

// Text to read and copy: read-only, selectable with the mouse (Ctrl+C copies the selection). `plain` is shown as it is, `rich`
// (styled markup the view-model made, `<u>` and the like) as markup; `leading` is the line height as a factor.
TextEdit {
    id: te

    property string plain: ""
    property string rich: ""
    property real leading: 1.3

    function markup(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br/>")
    }

    readOnly: true
    selectByMouse: true
    wrapMode: TextEdit.Wrap
    color: Theme.text
    selectionColor: Theme.s4
    selectedTextColor: Theme.bright
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSize
    renderType: Text.QtRendering
    textFormat: TextEdit.RichText
    height: contentHeight
    text: "<div style='line-height:" + Math.round(leading * 100) + "%'>" + (rich !== "" ? rich : markup(plain)) + "</div>"
}
