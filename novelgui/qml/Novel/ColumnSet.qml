pragma ComponentBehavior: Bound
import QtQuick

// Shared column widths of a table: the header and every row delegate read the same set, so they line up and a drag on the
// header splitter reflows all rows. columns: {key, title, width (px, default), min, flex (share of the free width), align}.
// A column with `flex` > 0 takes part of the width left after the fixed ones; `available` is the width of the row area.
QtObject {
    id: cs

    property var columns: []
    property real available: 0
    property var overrides: ({})
    readonly property var layout: compute(columns, available, overrides)
    readonly property real total: layout.total

    // the fixed width of a column, or -1 when it takes a share of the free width
    function fixedWidth(c, over) {
        return over[c.key] !== undefined ? over[c.key] : (c.flex > 0 ? -1 : c.width)
    }
    // total of the fixed widths and of the flex shares
    function totals(cols, over) {
        var t = { fixed: 0, flex: 0 }
        for (var i = 0; i < cols.length; ++i) {
            var w = fixedWidth(cols[i], over)
            if (w < 0)
                t.flex += cols[i].flex
            else
                t.fixed += w
        }
        return t
    }
    function compute(cols, avail, over) {
        var t = totals(cols, over), out = { cols: {}, total: 0 }
        var free = Math.max(0, avail - t.fixed)
        for (var i = 0; i < cols.length; ++i) {
            var w = fixedWidth(cols[i], over)
            w = Math.max(cols[i].min || 24, w < 0 ? free * cols[i].flex / t.flex : w)
            out.cols[cols[i].key] = { x: out.total, w: w }
            out.total += w
        }
        return out
    }
    function widthOf(key) {
        var c = layout.cols[key]
        return c ? c.w : 0
    }
    function xOf(key) {
        var c = layout.cols[key]
        return c ? c.x : 0
    }
    // a header drag: the column takes this width (the flex columns shrink or grow)
    function resize(key, w) {
        var o = Object.assign({}, overrides)
        o[key] = Math.max(24, w)
        overrides = o
    }
    function reset() {
        overrides = ({})
    }
    // saved widths of the user (window memory): {key: width}
    function state() {
        return Object.assign({}, overrides)
    }
}
