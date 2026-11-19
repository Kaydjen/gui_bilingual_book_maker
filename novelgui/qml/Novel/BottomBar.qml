pragma ComponentBehavior: Bound
import QtQuick

// The floating bottom bar, style B: one lifted capsule cut into segments by thin lines; with `sat` the round
// `•••` button hangs beside it and the capsule stays centred alone. segment: {text, kind, id, tip}; kind =
// "main" (bright, bold) | "" (dim) | "accent" (red) | "off" (faint).
Item {
    id: bar

    property var segments: []
    property bool sat: false
    property var satTip: ""
    signal activated(int index, string id)
    signal satClicked()

    implicitWidth: capsule.width
    implicitHeight: Theme.capsuleHeight

    Surface {
        id: capsule
        objectName: bar.objectName + "Capsule"
        width: strip.implicitWidth
        height: Theme.capsuleHeight
        level: 2
        radius: Theme.rCapsule

        Row {
            id: strip
            height: parent.height
            Repeater {
                model: bar.segments
                delegate: Item {
                    id: seg
                    required property int index
                    required property var modelData
                    readonly property string kind: modelData.kind || ""
                    readonly property bool off: kind === "off"
                    readonly property bool fixed: kind === "off" || kind === "capt"
                    width: label.implicitWidth + 32
                    height: strip.height

                    Rectangle {
                        visible: seg.index > 0
                        width: 1
                        height: parent.height
                        color: "#282828"
                    }
                    Rectangle {
                        anchors.fill: parent
                        anchors.leftMargin: seg.index > 0 ? 1 : 0
                        visible: !seg.fixed && segHover.hovered
                        color: Theme.lift2
                        topLeftRadius: seg.index === 0 ? Theme.rCapsule : 0
                        bottomLeftRadius: seg.index === 0 ? Theme.rCapsule : 0
                        topRightRadius: seg.index === bar.segments.length - 1 ? Theme.rCapsule : 0
                        bottomRightRadius: seg.index === bar.segments.length - 1 ? Theme.rCapsule : 0
                    }
                    AppText {
                        id: label
                        objectName: bar.objectName + "Text" + seg.index
                        anchors.centerIn: parent
                        text: seg.modelData.text
                        font.weight: seg.kind === "main" ? Font.DemiBold : Font.Normal
                        color: seg.off ? Theme.faint : seg.kind === "accent" ? Theme.accent : (seg.kind === "main" || (segHover.hovered && !seg.fixed) ? Theme.bright : Theme.dim)
                    }
                    HoverHandler { id: segHover; cursorShape: seg.fixed ? Qt.ArrowCursor : Qt.PointingHandCursor }
                    TapHandler { enabled: !seg.fixed; onTapped: bar.activated(seg.index, seg.modelData.id || "") }
                    TipArea { tip: seg.modelData.tip || "" }
                }
            }
        }
    }
    Sat {
        objectName: bar.objectName + "Sat"
        visible: bar.sat
        anchors.left: capsule.right
        anchors.leftMargin: 8
        anchors.verticalCenter: capsule.verticalCenter
        tip: bar.satTip
        onClicked: bar.satClicked()
    }
}
