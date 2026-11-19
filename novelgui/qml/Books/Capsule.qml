pragma ComponentBehavior: Bound
import QtQuick
import Novel

// The selection capsule (4.7): `54 chapters · 2697-2750 | Translate ›`, floating at the bottom of the chapter list. It exists
// only with a selection or while typing. The range text turns into a framed field on a click; Enter takes it, Esc restores,
// a wrong value flashes; `✕` at the right end of the open field = Esc. The right segment names the next step; it only
// opens that step, it never starts anything.
Item {
    id: cap

    property var books: null
    property bool wrong: false

    implicitWidth: pill.width
    implicitHeight: Theme.capsuleHeight

    function flash() {
        wrong = true
        shake.restart()
        reset.restart()
    }

    Surface {
        id: pill
        objectName: "capsule"
        width: lead.width + divider.width + next.width
        height: Theme.capsuleHeight
        level: 2
        radius: Theme.rCapsule

        Row {
            id: lead
            height: parent.height
            leftPadding: 18
            rightPadding: 16
            spacing: 6
            AppText {
                objectName: "capsuleCount"
                height: parent.height
                text: cap.books.capsuleCount
                color: Theme.bright
            }
            AppText {
                visible: !cap.books.typing
                height: parent.height
                text: "·"
                color: Theme.faint
            }
            AppText {
                id: range
                objectName: "capsuleRange"
                visible: !cap.books.typing
                height: parent.height
                text: cap.books.capsuleRange
                color: rangeHover.hovered ? Theme.bright : Theme.dim
                HoverHandler { id: rangeHover; cursorShape: Qt.IBeamCursor }
                TapHandler { onTapped: cap.books.beginTyping(range.text) }
                TipArea { tip: cap.books.tips.range }
            }
            Inset {
                id: well
                objectName: "capsuleField"
                visible: cap.books.typing
                anchors.verticalCenter: parent.verticalCenter
                width: 150
                height: 26
                edge: cap.wrong ? Theme.accent : Theme.fieldFocus
                TextInput {
                    id: input
                    objectName: "capsuleInput"
                    x: 8
                    width: parent.width - 30
                    height: parent.height
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.bright
                    selectionColor: Theme.s4
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize
                    clip: true
                    selectByMouse: true
                    onTextEdited: cap.books.typingEdited(text)
                    Keys.onReturnPressed: if (!cap.books.commitRange(text)) cap.flash()
                    Keys.onEscapePressed: cap.books.cancelTyping()
                    onActiveFocusChanged: if (!activeFocus && cap.books.typing && !cap.wrong) cap.books.commitRange(text)
                }
                AppText {
                    objectName: "capsuleClose"
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    height: parent.height
                    text: "✕"
                    font.family: Theme.symbolFamily
                    color: closeHover.hovered ? Theme.bright : Theme.dim
                    HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: cap.books.cancelTyping() }
                }
            }
        }
        Rectangle {
            id: divider
            anchors.left: lead.right
            width: 1
            height: parent.height
            color: "#282828"
        }
        Item {
            id: next
            anchors.left: divider.right
            width: label.implicitWidth + 32
            height: parent.height
            Rectangle {
                anchors.fill: parent
                visible: nextHover.hovered && !cap.books.typing
                color: Theme.lift2
                topRightRadius: Theme.rCapsule
                bottomRightRadius: Theme.rCapsule
            }
            AppText {
                id: label
                objectName: "capsuleNext"
                anchors.centerIn: parent
                text: cap.books.nextText
                font.weight: Font.DemiBold
                color: cap.books.typing ? Theme.faint : (cap.books.nextKind === "review" ? Theme.accent : Theme.bright)
            }
            HoverHandler { id: nextHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { enabled: !cap.books.typing; onTapped: cap.books.goNext() }
            TipArea { tip: cap.books.tips.next }
        }
    }
    Connections {
        target: cap.books
        function onTypingChanged() {
            if (cap.books.typing && !input.activeFocus) {
                input.text = cap.books.typingText
                input.forceActiveFocus()
                if (input.text.length < 3)
                    input.cursorPosition = input.text.length
                else
                    input.selectAll()
            }
        }
        function onRangeRejected() { cap.flash() }
    }
    SequentialAnimation {
        id: shake
        NumberAnimation { target: input; property: "x"; to: 14; duration: 40 }
        NumberAnimation { target: input; property: "x"; to: 2; duration: 60 }
        NumberAnimation { target: input; property: "x"; to: 11; duration: 50 }
        NumberAnimation { target: input; property: "x"; to: 8; duration: 50 }
    }
    Timer {
        id: reset
        interval: 700
        onTriggered: cap.wrong = false
    }
}
