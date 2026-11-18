pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

// The working word with a light wave that runs through its letters (the Translate step while a job runs). One
// SequentialAnimation drives `phase` across the letters and rests; each letter takes its brightness from the phase.
Item {
    id: wave

    property string text: ""
    property color color: Theme.dim
    property color peak: "#ffffff"
    property real phase: -1
    property real span: 2.2                 // letters wide the bright part is
    property int perLetter: 450
    property bool active: true

    implicitWidth: row.implicitWidth
    implicitHeight: row.implicitHeight

    function lit(i) {
        var d = Math.abs(phase - i)
        return d >= span ? 0 : 0.5 - 0.5 * Math.cos(Math.PI * (1 - d / span))
    }

    Row {
        id: row
        Repeater {
            model: wave.text.length
            delegate: AppText {
                required property int index
                text: wave.text.charAt(index)
                color: Theme.mix(wave.color, wave.peak, wave.lit(index))
            }
        }
    }
    SequentialAnimation {
        id: run
        objectName: "waveAnimation"
        loops: Animation.Infinite
        running: Visual.live && wave.visible && wave.active

        NumberAnimation {
            target: wave
            property: "phase"
            from: -wave.span
            to: wave.text.length + wave.span
            duration: (wave.text.length + 2 * wave.span) * wave.perLetter
        }
        PauseAnimation { duration: 600 }
    }
    Component.onCompleted: Visual.attach(Window.window)
    Window.onWindowChanged: Visual.attach(Window.window)
}
