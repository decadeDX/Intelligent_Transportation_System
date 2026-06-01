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

    ImageCarPersonDetectService {
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
                            visible: sourceImage.source === "" || sourceImage.status === Image.Error
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

                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 28

                            ColumnLayout {
                                spacing: 2

                                Label {
                                    text: qsTr("选择 YOLO 模型:")
                                    font.pixelSize: 12
                                    font.bold: true
                                }

                                ComboBox {
                                    id: modelComboBox
                                    Layout.preferredWidth: 140
                                    enabled: true
                                    model: ["yolov8n", "yolov8s", "yolo11n", "yolo11s"]
                                    currentIndex: 0

                                    background: Rectangle {
                                        implicitWidth: 140
                                        implicitHeight: 28
                                        color: AppTheme.comboBoxBackground
                                        border.color: AppTheme.comboBoxBorder
                                        border.width: 1
                                        radius: 2
                                    }
                                }
                            }

                            ColumnLayout {
                                spacing: 2

                                Label {
                                    text: qsTr("检测目标:")
                                    font.pixelSize: 12
                                    font.bold: true
                                }

                                ComboBox {
                                    id: targetComboBox
                                    Layout.preferredWidth: 140
                                    enabled: true
                                    model: [
                                        qsTr("全部"),
                                        qsTr("行人"),
                                        qsTr("汽车"),
                                        qsTr("自行车"),
                                        qsTr("摩托车"),
                                        qsTr("公交车"),
                                        qsTr("交通信号灯")
                                    ]
                                    currentIndex: 0

                                    background: Rectangle {
                                        implicitWidth: 140
                                        implicitHeight: 28
                                        color: AppTheme.comboBoxBackground
                                        border.color: AppTheme.comboBoxBorder
                                        border.width: 1
                                        radius: 2
                                    }
                                }
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
                            text: "开始检测"
                            enabled: !detectService.busy
                            onClicked: {
                                detectService.detect(
                                    root.selectedImageUrl,
                                    modelComboBox.currentText,
                                    targetComboBox.currentText
                                )
                            }

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

                Rectangle {
                    width: 1
                    height: contentContainer.height
                    color: AppTheme.dividerColor
                }

                Item {
                    id: rightPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12

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
                                text: "正在检测，请稍候..."
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

                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.fillWidth: true
                            text: detectService.statusMessage
                            font.pixelSize: 13
                            font.bold: true
                            color: "#333333"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            visible: detectService.statusMessage !== ""
                        }
                    }
                }
            }
        }
    }
}
