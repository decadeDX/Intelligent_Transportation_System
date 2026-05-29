import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16

        Label {
            text: qsTr("车位检测")
            font.bold: true
            font.pixelSize: 18
        }

        Label {
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: qsTr("功能开发中...")
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: "#999999"
        }
    }
}
