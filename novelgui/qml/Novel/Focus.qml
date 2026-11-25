pragma Singleton
pragma ComponentBehavior: Bound
import QtQuick
QtObject {
    property bool byKey: false
    property Item home: null            // the list of the screen that had the keys last: where an overlay gives the focus back
}
