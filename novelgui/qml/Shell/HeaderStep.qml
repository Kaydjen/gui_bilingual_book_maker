pragma ComponentBehavior: Bound
import QtQuick
import Novel

// One step of the path. `kind`: "" | "red" (Terms: pulses red three times and stays red) | "wave" (Translate while a job
// runs) | "attention" (Translate: a job needs the user, a slow red pulse). The active step is a small lifted pill.
Item {
    id: step

    property string text: ""
    property bool active: false
    property bool dim: false            // no library yet: the steps are dim and take no click
    property string kind: ""
    property var tip: ""
    property real pulse: 0
    property bool settled: false
    readonly property real value: kind === "red" ? (settled ? 1 : pulse) : (kind === "attention" ? 0.6 + 0.4 * pulse : 0)
    readonly property color base: dim ? Theme.faint : (active || hover.hovered ? Theme.bright : Theme.dim)
    readonly property color shown: Theme.mix(base, Theme.accent, value)
    signal clicked()

    implicitWidth: label.implicitWidth + 24
    implicitHeight: 28

    onKindChanged: {
        settled = false
        if (kind === "red")
            threePulses.restart()
    }
    Component.onCompleted: if (kind === "red") threePulses.restart()

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
