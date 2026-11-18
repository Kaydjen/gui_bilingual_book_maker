pragma ComponentBehavior: Bound
import QtQuick

// A baked soft shadow (9-slice image, see .ai/tools/qml/bake_shadows.py). Put it inside the item that floats;
// it grows past the parent by `pad` and sits under it. level: "sh1" | "sh2" | "sh3" | "glow" | "halo".
BorderImage {
    id: sh

    property string level: "sh1"
    readonly property var spec: Theme.shadows[level]

    x: -spec.pad
    y: -spec.pad + spec.dy
    z: -1
    width: parent ? parent.width + 2 * spec.pad : 0
    height: parent ? parent.height + 2 * spec.pad : 0
    source: Theme.assetsBase + level + ".png"
    border.left: spec.slice
    border.right: spec.slice
    border.top: spec.slice
    border.bottom: spec.slice
    smooth: true
    cache: true
    enabled: false
}
