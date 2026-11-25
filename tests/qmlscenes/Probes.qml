import QtQuick
import Novel

// Long names, a cut text with its tooltip, selectable text.
AppRoot {
    Rectangle {
        anchors.fill: parent
        color: Theme.pane
    }
    Item {
        x: 20
        y: 20
        width: 300
        height: 120
        Message {
            objectName: "longMessage"
            anchors.horizontalCenter: parent.horizontalCenter
            fact: [{ text: "Deleted ", kind: "" }, { text: "The Extremely Long Name of a Series That Cannot Fit Into Its Pane At All", kind: "n" }]
        }
    }
    AppText {
        objectName: "cutText"
        x: 20
        y: 160
        width: 90
        elide: Text.ElideRight
        text: "A name that is far too long"
        TruncTip {}
    }
    AppText {
        objectName: "shortText"
        x: 20
        y: 200
        width: 190
        elide: Text.ElideRight
        text: "Short"
        TruncTip {}
    }
    ReadText {
        objectName: "readProbe"
        x: 20
        y: 260
        width: 400
        plain: "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    }
}
