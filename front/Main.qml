import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import front

ApplicationWindow {
    id: root
    width: 1200
    height: 800
    visible: true
    title: qsTr("基于YOLO的智慧交通系统")
    visibility: Window.Maximized

    // property string statusText: qsTr("推理服务已就绪")

    BackendServerManager{
        id: backendServerManager

        onServerStartupFinished: function(success) {
                if (success) {
                    console.log("推理服务已就绪，可以发起检测请求")
                } else {
                    console.log("推理服务启动失败，请检查 backend 环境")
                }
            }
    }

    Component.onCompleted: backendServerManager.startServer();

    menuBar: MenuBar {
        Menu {
            title: qsTr("文件(&F)")
            Action {
                text: qsTr("打开")
                shortcut: StandardKey.Open
                onTriggered: console.log("打开文件")
            }
            MenuSeparator {}
            Action {
                text: qsTr("退出")
                shortcut: StandardKey.Quit
                onTriggered: Qt.quit()
            }
        }
        Menu {
            title: qsTr("设置(&S)")
            Action {
                text: qsTr("清除临时文件")
                onTriggered: console.log("清除临时文件")
            }
        }
        Menu {
            title: qsTr("帮助(&H)")
            Action {
                text: qsTr("关于")
                onTriggered: aboutDialog.open()
            }
        }
    }

    component StyledTabButton: TabButton {
        id: tabBtn
        property alias labelText: tabLabel.text

        background: Rectangle {
            color: tabBtn.checked ? AppTheme.tabActiveBackground : "transparent"
            border.color: AppTheme.tabBorderColor
            border.width: 1
            implicitHeight: 36
        }

        contentItem: Item {
            implicitWidth: tabLabel.implicitWidth + 24
            implicitHeight: tabLabel.implicitHeight + 8

            Text {
                id: tabLabel
                anchors.centerIn: parent
                color: tabBtn.checked ? AppTheme.tabActiveText : AppTheme.tabInactiveText
                font.pixelSize: 13
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: containsMouse ? Qt.PointingHandCursor : Qt.ArrowCursor
                acceptedButtons: Qt.NoButton
            }
        }
    }

    header: TabBar {
        id: tabBar
        currentIndex: stackLayout.currentIndex

        background: Rectangle {
            color: AppTheme.tabBarBackground
            implicitHeight: 36
        }

        StyledTabButton { labelText: qsTr("图片车辆行人检测") }
        StyledTabButton { labelText: qsTr("视频车辆行人检测") }
        StyledTabButton { labelText: qsTr("图片车牌检测") }
        StyledTabButton { labelText: qsTr("视频车牌检测") }
        StyledTabButton { labelText: qsTr("车速检测") }
        StyledTabButton { labelText: qsTr("车道检测") }
        StyledTabButton { labelText: qsTr("车位检测") }
        StyledTabButton { labelText: qsTr("车流量检测") }
        StyledTabButton { labelText: qsTr("交通标识检测") }
        StyledTabButton { labelText: qsTr("驾照识别") }
    }

    StackLayout {
        id: stackLayout
        anchors.fill: parent
        currentIndex: tabBar.currentIndex

        ImageCarPersonDected {}
        VideoCarPersonDected {}
        ImagePlateDected {}
        VideoPlateDected {}
        CarSpeedDected {}
        LaneDected {}
        ParkingSpaceDected {}
        TrafficFlowDected {}
        TrafficSignDected {}
        DriverLicenseDected {}
    }

    footer: Rectangle {
        id: statusBar
        height: 30
        color: AppTheme.statusBarBackground
        border.color: AppTheme.statusBarBorder
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.margins: 6
            spacing: 10

            Label {
                text: ""
                Layout.fillWidth: true
                font.pixelSize: 13
                verticalAlignment: Text.AlignVCenter
            }

            // Label {
            //     text: ""
            //     font.pixelSize: 13
            //     verticalAlignment: Text.AlignVCenter
            //     color: AppTheme.statusSuccessColor

            // }

            Label {
                text: backendServerManager.statusText
                color: backendServerManager.serverReady ? AppTheme.statusSuccessColor
                        : (backendServerManager.serverFailed ? AppTheme.statusErrorColor
                                                            : AppTheme.statusTextColor)
            }

            Label {
                text: "version: v1.0.0"
                font.pixelSize: 12
                color: AppTheme.statusTextColor
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    Dialog {
        id: aboutDialog
        title: qsTr("基于YOLO智慧交通系统项目演示")
        standardButtons: Dialog.Ok
        modal: true
        anchors.centerIn: parent

        Text {
            text: qsTr("基于 Qt Quick 的 YOLO 目标检测演示程序\n\n\n\n© 2026 作者：丁鑫")
            font.pixelSize: 14
            wrapMode: Text.Wrap
            width: 400
        }
    }
}
