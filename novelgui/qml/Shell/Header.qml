pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Novel

// The header (window_spec 1.1-1.7, 9.10): `series · book` dim at the left, the path in a fixed middle column, the gear
// at the right edge that never moves. With the custom frame `— ▢ ✕` slide in to the LEFT of the gear when the pointer
// touches the top edge or the hot zone, and go 600 ms after it leaves. The header reports its layout to `frame`.
Item {
    id: header

    property var app: null
    property var frame: null
    property bool forceButtons: false
    readonly property bool custom: frame !== null && frame.custom
    readonly property bool maximized: Window.window !== null && Window.window.visibility === Window.Maximized
    property bool shown: false
    property real reveal: shown || forceButtons ? 1 : 0
    readonly property bool wanted: custom && ((frame !== null && frame.edgeHot) || zone.hovered || cluster.hovered)
    signal gearClicked()

    height: 46

    function box(item) {
        var p = item.mapToItem(null, 0, 0)
        return [p.x, p.y, item.width, item.height]
    }
    function report() {
        if (frame === null)
            return
        var r = [box(context), box(gear), box(hot)]
        for (var i = 0; i < stepRow.count; ++i)
            r.push(box(stepRow.itemAt(i)))
        var full = reveal > 0.99
        if (full)
            r.push(box(btnMin), box(btnClose))
        frame.setRegions(height, r, full ? box(btnMax) : [])
    }
    function toggleMax() {
        if (Window.window.visibility === Window.Maximized)
            Window.window.showNormal()
        else
            Window.window.showMaximized()
    }
    onWantedChanged: {
        if (wanted) {
            hideTimer.stop()
            shown = true
        } else {
            hideTimer.restart()
        }
    }
    onWidthChanged: relayout.restart()
    onRevealChanged: relayout.restart()
    Component.onCompleted: relayout.restart()
    Timer {
        id: hideTimer
        interval: 600
        onTriggered: header.shown = false
    }
    Timer {
        id: relayout
        interval: 60
        onTriggered: header.report()
    }

    // series · book (click = Books, 1.3)
    AppText {
        id: context
        objectName: "contextLine"
        x: 16
        width: Math.min(implicitWidth, Math.max(0, stepCol.x - 40))
        height: parent.height
        elide: Text.ElideRight
        text: header.app ? header.app.contextLine : ""
        color: ctxHover.hovered ? Theme.bright : Theme.dim
        HoverHandler { id: ctxHover; enabled: context.text !== ""; cursorShape: Qt.PointingHandCursor }
        TapHandler { enabled: context.text !== ""; onTapped: header.app.go("books") }
        TipArea { tip: context.text !== "" && header.app ? header.app.tips.context : "" }
    }

    // the path, always in the same place
    Item {
        id: stepCol
        objectName: "steps"
        anchors.horizontalCenter: parent.horizontalCenter
        y: (parent.height - height) / 2
        width: stepRow.width
        height: 28
        Row {
            id: stepRow
            readonly property int count: repeater.count
            function itemAt(i) {
                return repeater.itemAt(i)
            }
            Repeater {
                id: repeater
                model: header.app ? header.app.steps : []
                delegate: Row {
                    id: cell
                    required property int index
                    required property var modelData
                    AppText {
                        visible: cell.index > 0
                        height: 28
                        text: "›"
                        color: Theme.faint
                        leftPadding: 2
                        rightPadding: 2
                    }
                    HeaderStep {
                        id: stepItem
                        objectName: "step_" + cell.modelData.id
                        text: cell.modelData.text
                        active: header.app.screen === cell.modelData.id
                        dim: header.app.stepsDim
                        kind: cell.modelData.id === "terms" ? header.app.termsState
                              : (cell.modelData.id === "translate" ? header.app.translateState : "")
                        tip: cell.modelData.id === "translate" ? header.app.translateTip
                             : (cell.modelData.id === "terms" && header.app.termsState === "red" ? header.app.tips.termsRed
                                : header.app.tips[cell.modelData.id])
                        onClicked: header.app.go(cell.modelData.id)
                    }
                }
            }
        }
    }

    // the hot zone left of the gear (owner 2026-11-19: taller than the first 10 px, about half the header)
    Item {
        id: hot
        objectName: "titleHotZone"
        x: gear.x - 140
        y: 0
        width: 140
        height: 24
        visible: header.custom
        HoverHandler { id: zone }
    }

    // the three buttons: they slide in to the left of the gear
    Row {
        id: cluster
        objectName: "titleButtons"
        readonly property bool hovered: header.reveal > 0.5 && (hoverCluster.hovered || btnMax.hovered)
        visible: header.custom && header.reveal > 0
        anchors.right: gear.left
        anchors.rightMargin: 4
        y: (parent.height - height) / 2
        spacing: 2
        opacity: header.reveal
        transform: Translate { x: (1 - header.reveal) * 24 }
        Behavior on opacity { NumberAnimation { duration: 150 } }
        HoverHandler { id: hoverCluster }
        TitleButton {
            id: btnMin
            objectName: "btnMin"
            enabled: header.reveal > 0.5
            glyph: "—"
            tip: header.app ? header.app.tips.min : ""
            onClicked: Window.window.showMinimized()
        }
        TitleButton {
            id: btnMax
            objectName: "btnMax"
            enabled: header.reveal > 0.5
            glyph: header.maximized ? "❐" : "▢"
            hot: header.frame !== null && header.frame.maxHot
            tip: header.app ? (header.maximized ? header.app.tips.restore : header.app.tips.max) : ""
            onClicked: header.toggleMax()
        }
        TitleButton {
            id: btnClose
            objectName: "btnClose"
            enabled: header.reveal > 0.5
            glyph: "✕"
            tip: header.app ? header.app.tips.close : ""
            onClicked: Window.window.close()
        }
    }
    Behavior on reveal { NumberAnimation { duration: 150 } }

    // the gear: never moves, brighter on hover, never darker than its ground
    Item {
        id: gear
        objectName: "gear"
        anchors.right: parent.right
        anchors.rightMargin: 14
        y: (parent.height - height) / 2
        width: 34
        height: 34
        AppText {
            anchors.centerIn: parent
            text: "⚙︎"
            font.pixelSize: Theme.fontGear
            font.family: Theme.symbolFamily
            color: gearHover.hovered || header.app.settingsOpen ? Theme.bright : Theme.dim
        }
        HoverHandler { id: gearHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: header.gearClicked() }
        TipArea { tip: header.app ? header.app.tips.gear : "" }
        FocusRing { target: gear; inner: Theme.rControl }
        activeFocusOnTab: true
        Keys.onReturnPressed: header.gearClicked()
        Keys.onSpacePressed: header.gearClicked()
    }
}
