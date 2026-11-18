pragma Singleton
pragma ComponentBehavior: Bound
import QtQuick

// Tooltip controller (window_spec 9.6): armed when the pointer enters an element, shown after 600 ms, kept
// while the pointer stays on the element, gone when it leaves, a press or a key. Texts are data: a string, or
// {text, facts: [[name, value], ...]}, or the pair [text, facts] as tips.py keeps them.
QtObject {
    id: tips

    property var owner: null
    property string text: ""
    property var facts: []
    property point at: Qt.point(0, 0)
    property bool shown: false
    property bool visit: false           // the pointer is still on the element that armed

    property Timer delay: Timer {
        interval: Theme.tipDelay
        onTriggered: tips.shown = tips.text !== ""
    }

    function normalize(tip) {
        if (typeof tip === "string")
            return { text: tip, facts: [] }
        if (Array.isArray(tip))
            return { text: tip[0], facts: tip[1] || [] }
        return { text: (tip && tip.text) || "", facts: (tip && tip.facts) || [] }
    }

    function arm(who, tip, pos) {
        var t = normalize(tip)
        if (!t.text)
            return
        owner = who
        visit = true
        text = t.text
        facts = t.facts
        at = pos
        shown = false
        delay.restart()
    }

    function showNow(who, tip, pos) {
        arm(who, tip, pos)
        delay.stop()
        shown = text !== ""
    }

    function leave(who) {
        if (who !== owner)
            return
        visit = false
        dismiss()
        owner = null
    }

    // a press or a key: the tip goes, and does not come back while the pointer rests on the same element
    function dismiss() {
        delay.stop()
        shown = false
    }
}
