pragma Singleton
import QtQuick

QtObject {
    readonly property color tabBarBackground: "#333333"
    readonly property color tabBorderColor: "#555555"
    readonly property color tabActiveBackground: "#ffffff"
    readonly property color tabActiveText: "#000000"
    readonly property color tabInactiveText: "#ffffff"

    readonly property color contentBackground: "#ffffff"
    readonly property color dividerColor: "#cccccc"
    readonly property color statusBarBackground: "#f0f0f0"
    readonly property color statusBarBorder: "#cccccc"
    readonly property color statusTextColor: "#666666"
    readonly property color statusSuccessColor: "#008000"
    readonly property color statusErrorColor: "#cc0000"

    readonly property color uploadButtonNormal: "#4CAF50"
    readonly property color uploadButtonHover: "#66BB6A"
    readonly property color uploadButtonPressed: "#388E3C"

    readonly property color detectButtonNormal: "#2196F3"
    readonly property color detectButtonHover: "#42A5F5"
    readonly property color detectButtonPressed: "#1976D2"

    readonly property color comboBoxBackground: "#e0e0e0"
    readonly property color comboBoxBorder: "#bdbdbd"
}
