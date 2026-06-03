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
                text: qsTr("清理文件")
                onTriggered: clearFilesConfirmDialog.open()
            }
            Action {
                text: qsTr("刷新界面")
                onTriggered: refreshConfirmDialog.open()
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

    function pageLoader(index) {
        switch (index) {
        case 0: return imageCarPersonLoader
        case 1: return videoCarPersonLoader
        case 2: return imagePlateLoader
        case 3: return videoPlateLoader
        case 4: return carSpeedLoader
        case 5: return laneLoader
        case 6: return parkingSpaceLoader
        case 7: return trafficFlowLoader
        case 8: return trafficSignLoader
        case 9: return driverLicenseLoader
        default: return null
        }
    }

    function pageComponent(index) {
        switch (index) {
        case 0: return imageCarPersonPage
        case 1: return videoCarPersonPage
        case 2: return imagePlatePage
        case 3: return videoPlatePage
        case 4: return carSpeedPage
        case 5: return lanePage
        case 6: return parkingSpacePage
        case 7: return trafficFlowPage
        case 8: return trafficSignPage
        case 9: return driverLicensePage
        default: return null
        }
    }

    function refreshCurrentPage() {
        const loader = root.pageLoader(stackLayout.currentIndex)
        const component = root.pageComponent(stackLayout.currentIndex)
        if (!loader || !component)
            return

        loader.sourceComponent = null
        Qt.callLater(function() {
            loader.sourceComponent = component
            refreshResultDialog.open()
        })
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

        Loader { id: imageCarPersonLoader; sourceComponent: imageCarPersonPage }
        Loader { id: videoCarPersonLoader; sourceComponent: videoCarPersonPage }
        Loader { id: imagePlateLoader; sourceComponent: imagePlatePage }
        Loader { id: videoPlateLoader; sourceComponent: videoPlatePage }
        Loader { id: carSpeedLoader; sourceComponent: carSpeedPage }
        Loader { id: laneLoader; sourceComponent: lanePage }
        Loader { id: parkingSpaceLoader; sourceComponent: parkingSpacePage }
        Loader { id: trafficFlowLoader; sourceComponent: trafficFlowPage }
        Loader { id: trafficSignLoader; sourceComponent: trafficSignPage }
        Loader { id: driverLicenseLoader; sourceComponent: driverLicensePage }
    }

    Component { id: imageCarPersonPage; ImageCarPersonDected {} }
    Component { id: videoCarPersonPage; VideoCarPersonDected {} }
    Component { id: imagePlatePage; ImagePlateDected {} }
    Component { id: videoPlatePage; VideoPlateDected {} }
    Component { id: carSpeedPage; CarSpeedDected {} }
    Component { id: lanePage; LaneDected {} }
    Component { id: parkingSpacePage; ParkingSpaceDected {} }
    Component { id: trafficFlowPage; TrafficFlowDected {} }
    Component { id: trafficSignPage; TrafficSignDected {} }
    Component { id: driverLicensePage; DriverLicenseDected {} }

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

    Dialog {
        id: clearFilesConfirmDialog
        title: qsTr("清理文件")
        modal: true
        anchors.centerIn: parent
        width: 380

        Text {
            text: qsTr("是否清除 upload/source 和 upload/detected 下的文件？")
            font.pixelSize: 14
            wrapMode: Text.Wrap
            width: parent.width
        }

        footer: DialogButtonBox {
            Button {
                text: qsTr("是")
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
            Button {
                text: qsTr("否")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }

            onAccepted: {
                clearFilesConfirmDialog.close()
                const success = backendServerManager.clearTemporaryFiles()
                clearFilesResultDialog.clearSucceeded = success
                clearFilesResultDialog.open()
            }
            onRejected: clearFilesConfirmDialog.close()
        }
    }

    Dialog {
        id: clearFilesResultDialog
        property bool clearSucceeded: true

        title: clearSucceeded ? qsTr("清理完成") : qsTr("清理失败")
        standardButtons: Dialog.Ok
        modal: true
        anchors.centerIn: parent
        width: 340

        Text {
            text: clearFilesResultDialog.clearSucceeded
                  ? qsTr("清除相关文件完毕")
                  : qsTr("清除相关文件失败，请检查文件是否正在被占用")
            font.pixelSize: 14
            wrapMode: Text.Wrap
            width: parent.width
        }
    }

    Dialog {
        id: refreshConfirmDialog
        title: qsTr("刷新界面")
        modal: true
        anchors.centerIn: parent
        width: 380

        Text {
            text: qsTr("是否刷新当前界面？当前页面的选择和结果将被清空。")
            font.pixelSize: 14
            wrapMode: Text.Wrap
            width: parent.width
        }

        footer: DialogButtonBox {
            Button {
                text: qsTr("是")
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
            Button {
                text: qsTr("否")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }

            onAccepted: {
                refreshConfirmDialog.close()
                root.refreshCurrentPage()
            }
            onRejected: refreshConfirmDialog.close()
        }
    }

    Dialog {
        id: refreshResultDialog
        title: qsTr("刷新完成")
        standardButtons: Dialog.Ok
        modal: true
        anchors.centerIn: parent
        width: 300

        Text {
            text: qsTr("当前界面已刷新")
            font.pixelSize: 14
            wrapMode: Text.Wrap
            width: parent.width
        }
    }
}
