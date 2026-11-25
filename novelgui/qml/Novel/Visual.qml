pragma Singleton
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

// Is the window worth animating for? Visible, not minimized and the application is active.
// Every `loops: Animation.Infinite` binds `running` to this (review_window_arch D7).
QtObject {
    id: visual

    property var window: null
    // tests and the shell may force the answer; null = ask the window
    property var override: null
    // follows the window's visibility signal (a binding on window.visible alone is not re-evaluated reliably)
    property bool shown: true

    readonly property bool live: {
        if (override !== null)
            return override
        return Application.state === Qt.ApplicationActive && (window === null || shown)
    }

    property Connections watcher: Connections {
        target: visual.window
        function onVisibilityChanged(v) {
            visual.shown = v !== Window.Hidden && v !== Window.Minimized
        }
    }

    // an animated component calls this when it knows its window; the first window seen is the one that counts
    function attach(w) {
        if (window === null && w) {
            window = w
            shown = w.visibility !== Window.Hidden && w.visibility !== Window.Minimized
        }
    }
}
