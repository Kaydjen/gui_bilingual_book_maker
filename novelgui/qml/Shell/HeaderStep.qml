pragma ComponentBehavior: Bound
import QtQuick
import Novel

// One step of the path. `kind`: "" | "red" (Terms: pulses red three times and stays red) | "wave" (Translate while a job
// runs) | "attention" (Translate: a job needs the user, a slow red pulse) | "ready" (Export: every chosen chapter is translated: it
// glows once and stays bright). The active step is a small lifted pill.
Item {
    id: step

    property string text: ""
    property bool active: false
    property bool dim: false            // no library yet: the steps are dim and take no click
    property string kind: ""
    property var tip: ""
    property real progress: -1          // the book scan under the word (Terms): a thin line, nothing moves
    property real pulse: 0
    property bool settled: false
    property real glow: 0
    readonly property real value: kind === "red" ? (settled ? 1 : pulse) : (kind === "attention" ? 0.6 + 0.4 * pulse : 0)
    readonly property color base: dim ? Theme.faint : (active || hover.hovered || kind === "ready" ? Theme.bright : Theme.dim)
    readonly property color shown: Theme.mix(base, Theme.accent, value)
    signal clicked()

    implicitWidth: label.implicitWidth + 24
    implicitHeight: 28

    onKindChanged: {
        settled = false
        if (kind === "red")
            threePulses.restart()
        if (kind === "ready")
            glowOnce.restart()
    }
    Component.onCompleted: {
        if (kind === "red")
            threePulses.restart()
        if (kind === "ready")
            glowOnce.restart()
    }

    Item {
        objectName: "stepGlow_" + step.text
        anchors.fill: parent
        visible: step.glow > 0
        opacity: step.glow
        Shadow { level: "glow" }
    }
    Surface {
        anchors.fill: parent
        visible: step.active && !step.dim
        level: 1
        radius: Theme.rControl
        color: Theme.lift
    }
    AppText {
        id: label
        visible: step.kind !== "wave"
        anchors.centerIn: parent
        text: step.text
        color: step.shown
    }
    Rectangle {
        objectName: "stepScan_" + step.text
        visible: step.progress >= 0
        x: 12
        y: parent.height - 3
        width: parent.width - 24
        height: 2
        color: Theme.s3
        Rectangle {
            width: parent.width * Math.min(1, step.progress / 100)
            height: 2
            color: Theme.dim
        }
    }
    LetterWave {
        id: wave
        objectName: "stepWave"
        visible: step.kind === "wave"
        anchors.centerIn: parent
        text: step.text
        color: step.active ? Theme.bright : Theme.dim
        active: step.kind === "wave"
    }
    HoverHandler {
        id: hover
        enabled: !step.dim
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        enabled: !step.dim
        onTapped: step.clicked()
    }
    TipArea { tip: step.tip }

    SequentialAnimation {
        id: glowOnce
        NumberAnimation { target: step; property: "glow"; from: 0; to: 1; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { target: step; property: "glow"; to: 0; duration: 2300; easing.type: Easing.InOutSine }
    }
    SequentialAnimation {
        id: threePulses
        loops: 3
        NumberAnimation { target: step; property: "pulse"; from: 0; to: 1; duration: 220 }
        NumberAnimation { target: step; property: "pulse"; from: 1; to: 0.15; duration: 260 }
        onFinished: step.settled = true
    }
    SequentialAnimation {
        loops: Animation.Infinite
        running: Visual.live && step.kind === "attention"
        NumberAnimation { target: step; property: "pulse"; from: 0; to: 1; duration: 900; easing.type: Easing.InOutSine }
        NumberAnimation { target: step; property: "pulse"; from: 1; to: 0; duration: 900; easing.type: Easing.InOutSine }
    }
}
