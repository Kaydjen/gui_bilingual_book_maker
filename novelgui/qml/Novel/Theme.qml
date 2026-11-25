pragma Singleton
pragma ComponentBehavior: Bound
import QtQuick

// Style B . Lifted (window_spec 9.13): black + one red, depth instead of borders.
// Values come from .ai/mockups/mock.css and full/lifted.css.
QtObject {
    id: theme

    // ---- surfaces
    readonly property color bg: "#000000"
    readonly property color s1: "#0b0b0b"
    readonly property color s2: "#161616"
    readonly property color s3: "#222222"
    readonly property color s4: "#2e2e2e"
    readonly property color pane: "#0a0a0a"
    readonly property color lift: "#1c1c1c"
    readonly property color lift2: "#262626"
    readonly property color pill: "#171717"
    readonly property color pillHover: "#202020"
    readonly property color pillOff: "#0e0e0e"
    readonly property color menu: "#1a1a1a"
    readonly property color panel: "#171717"
    readonly property color field: "#060606"
    readonly property color fieldLine: "#1e1e1e"
    readonly property color fieldFocus: "#3a3a3a"
    readonly property color rowHover: "#121212"
    readonly property color rowSelected: "#1a1a1a"
    readonly property color rowLine: "#161616"
    readonly property color divider: "#272727"
    readonly property color veil: Qt.rgba(0, 0, 0, 0.5)
    readonly property color hairline: Qt.rgba(1, 1, 1, 0.08)
    readonly property color ring: "#b8b8b8"

    // ---- the four brightness levels of text (they must stay visibly apart)
    readonly property color bright: "#f4f4f4"
    readonly property color text: "#dedede"
    readonly property color dim: "#8a8a8a"
    readonly property color faint: "#5a5a5a"

    // ---- the one red (a problem the user must act on)
    readonly property color accent: "#e5383b"
    readonly property color accentHover: "#ef4b4e"

    // ---- radii
    readonly property int rControl: 7
    readonly property int rRow: 6
    readonly property int rMenu: 9
    readonly property int rPane: 10
    readonly property int rPanel: 14
    readonly property int rCapsule: 19
    readonly property int rField: 6

    // ---- spacing and sizes
    readonly property int gap: 8
    readonly property int pad: 16
    readonly property int rowHeight: 30
    readonly property int pillHeight: 30
    readonly property int capsuleHeight: 38
    readonly property int satSize: 38
    readonly property int minWidth: 820
    readonly property int minHeight: 600

    // ---- fonts
    readonly property int fontSize: 13
    readonly property int fontSmall: 11
    readonly property int fontTitle: 14
    readonly property int fontGear: 17
    readonly property var installed: Qt.fontFamilies()
    readonly property string fontFamily: {
        var want = ["Segoe UI", "Noto Sans", "DejaVu Sans", "Ubuntu", "Cantarell"]
        for (var i = 0; i < want.length; ++i)
            if (installed.indexOf(want[i]) >= 0)
                return want[i]
        return Application.font.family
    }

    // symbols (gear, window buttons): a monochrome font, never the colour emoji one
    readonly property string symbolFamily: {
        var want = ["Segoe UI Symbol", "Noto Sans Symbols2", "DejaVu Sans", "Noto Sans"]
        for (var i = 0; i < want.length; ++i)
            if (installed.indexOf(want[i]) >= 0)
                return want[i]
        return fontFamily
    }

    // ---- motion
    readonly property int tipDelay: 600
    readonly property int durFast: 150
    readonly property int durPop: 160
    readonly property int durPanel: 200
    readonly property int durShake: 220
    readonly property var easeBezier: [0.2, 0.8, 0.2, 1, 1, 1]
    readonly property int easeType: Easing.OutCubic

    // ---- baked shadows: pad = how far the soft edge reaches, dy = vertical offset (see .ai/tools/qml/bake_shadows.py)
    readonly property var shadows: ({
        "sh1": { pad: 24, dy: 3, slice: 48 },
        "sh2": { pad: 52, dy: 10, slice: 76 },
        "sh3": { pad: 128, dy: 26, slice: 152 },
        "glow": { pad: 24, dy: 0, slice: 48 },
        "halo": { pad: 24, dy: 0, slice: 48 }
    })
    readonly property url assetsBase: Qt.resolvedUrl("../assets/")

    // brighten a colour by mixing with white (used for hover of text)
    function mix(a, b, f) {
        return Qt.rgba(a.r + (b.r - a.r) * f, a.g + (b.g - a.g) * f, a.b + (b.b - a.b) * f, 1)
    }
}
