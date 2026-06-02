import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import front

Item {
    id: root

    readonly property real containerMarginRatio: 0.01
    readonly property int controlSpacing: 8
    readonly property int controlBottomMargin: 24

    property url selectedImageUrl: ""

    ImagePlateDetectService {
        id: detectService
    }

    FileDialog {
        id: imageFileDialog
        title: qsTr("选择图片")
        nameFilters: [qsTr("图片文件 (*.png *.jpg *.jpeg *.bmp)")]
        onAccepted: {
            root.selectedImageUrl = selectedFile
            sourceImage.source = selectedFile
        }
    }

    Rectangle {
        anchors.fill: parent
        color: AppTheme.contentBackground

        Item {
            id: contentContainer
            anchors.fill: parent
            anchors.margins: root.width * containerMarginRatio

            Row {
                anchors.fill: parent
                spacing: 0

                // ==================== 左栏：原图 + 控件 ====================
                Item {
                    id: leftPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    Item {
                        id: imageArea
                        anchors.top: leftPanel.top
                        anchors.left: leftPanel.left
                        anchors.right: leftPanel.right
                        anchors.bottom: controlsBlock.top
                        anchors.bottomMargin: 20

                        Image {
                            id: sourceImage
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectFit
                            source: ""
                            mipmap: true
                        }

                        Label {
                            anchors.centerIn: parent
                            text: qsTr("请上传待检测图片")
                            color: "#999999"
                            font.pixelSize: 14
                            visible: sourceImage.source == "" || sourceImage.status === Image.Error
                        }
                    }

                    ColumnLayout {
                        id: controlsBlock
                        anchors.bottom: leftPanel.bottom
                        anchors.bottomMargin: controlBottomMargin
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        width: leftPanel.width
                        spacing: controlSpacing

                        Button {
                            id: uploadButton
                            Layout.alignment: Qt.AlignHCenter
                            text: qsTr("上传图片")
                            enabled: true
                            onClicked: imageFileDialog.open()

                            background: Rectangle {
                                implicitWidth: 110
                                implicitHeight: 30
                                radius: 4
                                color: uploadButton.down ? AppTheme.uploadButtonPressed
                                      : (uploadButton.hovered ? AppTheme.uploadButtonHover : AppTheme.uploadButtonNormal)
                            }

                            contentItem: Text {
                                text: uploadButton.text
                                color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 13
                            }
                        }

                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: detectService.errorMessage
                            font.pixelSize: 12
                            color: "#d9534f"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            Layout.maximumWidth: leftPanel.width - 40
                            visible: detectService.errorMessage !== ""
                        }

                        Button {
                            id: detectButton
                            Layout.alignment: Qt.AlignHCenter
                            text: qsTr("开始检测")
                            enabled: !detectService.busy && root.selectedImageUrl != ""
                            onClicked: detectService.detect(root.selectedImageUrl)

                            background: Rectangle {
                                implicitWidth: 110
                                implicitHeight: 30
                                radius: 4
                                color: detectButton.down ? AppTheme.detectButtonPressed
                                      : (detectButton.hovered ? AppTheme.detectButtonHover : AppTheme.detectButtonNormal)
                                opacity: detectButton.enabled ? 1.0 : 0.6
                            }

                            contentItem: Text {
                                text: detectButton.text
                                color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 13
                            }
                        }
                    }
                }

                // ==================== 分隔线 ====================
                Rectangle {
                    width: 1
                    height: contentContainer.height
                    color: AppTheme.dividerColor
                }

                // ==================== 右栏：结果图 + 车牌列表 ====================
                Item {
                    id: rightPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12

                        // 结果图
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            Image {
                                id: resultImage
                                anchors.fill: parent
                                fillMode: Image.PreserveAspectFit
                                source: detectService.resultImageUrl
                                mipmap: true
                            }

                            Label {
                                anchors.centerIn: parent
                                text: qsTr("正在检测，请稍候...")
                                color: "#999999"
                                font.pixelSize: 14
                                visible: detectService.busy
                            }

                            BusyIndicator {
                                anchors.centerIn: parent
                                running: detectService.busy
                                visible: detectService.busy
                            }
                        }

                        // 状态信息
                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.fillWidth: true
                            text: detectService.statusMessage
                            font.pixelSize: 13
                            font.bold: true
                            color: detectService.errorMessage !== "" ? "#d9534f" : "#333333"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            visible: detectService.statusMessage !== ""
                        }

                        // 车牌列表
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 120
                            Layout.maximumHeight: 160
                            visible: detectService.plateList.length > 0
                            clip: true

                            Column {
                                width: parent.width
                                spacing: 4

                                Repeater {
                                    model: detectService.plateList

                                    delegate: Rectangle {
                                        width: rightPanel.width - 20
                                        height: 36
                                        radius: 4
                                        color: "#f9f9f9"
                                        border.color: "#e0e0e0"
                                        border.width: 1

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 12

                                            Text {
                                                text: modelData.plateno || ""
                                                font.pixelSize: 15
                                                font.bold: true
                                                color: "#222222"
                                            }

                                            Rectangle {
                                                width: plateColorLabel.implicitWidth + 12
                                                height: 22
                                                radius: 3
                                                color: _plateColorBg(modelData.platecolor || "")

                                                Text {
                                                    id: plateColorLabel
                                                    anchors.centerIn: parent
                                                    text: modelData.platecolor || ""
                                                    font.pixelSize: 11
                                                    color: "#ffffff"
                                                }
                                            }

                                            Text {
                                                text: modelData.city || ""
                                                font.pixelSize: 12
                                                color: "#666666"
                                            }

                                            Item { Layout.fillWidth: true }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    /// 车牌颜色 → 色块背景色
    function _plateColorBg(colorName) {
        switch (colorName) {
            case "蓝色": return "#1565C0"
            case "绿色": return "#2E7D32"
            case "黄色": return "#F9A825"
            case "黑色": return "#212121"
            case "白色": return "#BDBDBD"
            default:     return "#757575"
        }
    }
}
