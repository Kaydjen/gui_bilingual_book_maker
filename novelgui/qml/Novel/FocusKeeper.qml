pragma ComponentBehavior: Bound
import QtQuick

// What an overlay (menu, list, panel) does with the keyboard focus: remember the item that had it when the overlay opens, give
// it back when the overlay closes (when that item is gone or hidden: the main list of the screen, Focus.home).
QtObject {
    id: keeper

    property Item owner: null
    property Item saved: null

    function inside(item) {
        for (var p = item; p; p = p.parent)
            if (p === keeper.owner)
                return true
        return false
    }
    function current() {
        var w = owner ? owner.Window.window : null
        return w ? w.activeFocusItem : null
    }
    function remember() {
        var f = current()
        saved = f && !inside(f) ? f : null
    }
    // only when the focus is still in the overlay (or nowhere): an action that already moved it elsewhere keeps it
    function restore() {
        var f = current()
        if (f && !inside(f)) {
            saved = null
            return
        }
        var target = saved && saved.visible ? saved : (Focus.home && Focus.home.visible ? Focus.home : null)
        saved = null
        if (target)
            target.forceActiveFocus()
    }
}
