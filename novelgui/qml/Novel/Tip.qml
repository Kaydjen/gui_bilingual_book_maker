pragma ComponentBehavior: Bound
import QtQuick

// The tooltip bubble: a plain explanation, then under a thin line a fixed list of `name  value` facts.
Surface {
    id: tip

    property string text: ""
    property var facts: []
    property bool onCard: false
    readonly property real maxWidth: 300

    color: onCard ? Theme.menuOnPanel : Theme.menu
    radius: Theme.rControl
    level: 2
    width: Math.max(Math.min(maxWidth - 20, ruler.implicitWidth), factsBox.visible ? factsBox.implicitWidth : 0) + 20
    height: col.implicitHeight + 12

    AppText {
        id: ruler
        visible: false
        text: tip.text
    }

    Column {
        id: col
        x: 10
        y: 6
        spacing: 6
        width: tip.width - 20

        AppText {
            id: body
            objectName: tip.objectName + "Text"
            width: parent.width
            text: tip.text
            wrapMode: Text.Wrap
            lineHeight: 1.1
        }
        Rectangle {
            visible: tip.facts.length > 0
            width: parent.width
            height: 1
            color: Theme.divider
        }
        Grid {
            id: factsBox
            visible: tip.facts.length > 0
            columns: 2
            columnSpacing: 20
            rowSpacing: 2
            Repeater {
                model: tip.facts.length * 2
                delegate: AppText {
                    required property int index
                    readonly property var pair: tip.facts[Math.floor(index / 2)]
                    text: index % 2 === 0 ? pair[0] : pair[1]
                    color: index % 2 === 0 || pair[1] === "no" || pair[1] === "-" ? Theme.dim : Theme.text
                }
            }
        }
    }
}
