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
    readonly property bool isIdCardMode: typeComboBox.currentIndex === 1
    readonly property string recognitionType: root.isIdCardMode ? "id_card" : "driver_license"
    readonly property var tableRows: root.isIdCardMode ? root.idCardRows() : root.driverLicenseRows()

    DriverLicenseDetectService {
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
                            text: qsTr("请上传待识别图片")
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
                            enabled: !detectService.busy
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
                            spacing: 8

                            Label {
                                text: qsTr("识别类型：")
                                font.pixelSize: 13
                                color: "#555555"
                            }

                            ComboBox {
                                id: typeComboBox
                                model: [qsTr("驾驶证"), qsTr("身份证")]
                                currentIndex: 0
                                enabled: !detectService.busy

                                background: Rectangle {
                                    implicitWidth: 110
                                    implicitHeight: 30
                                    radius: 4
                                    color: typeComboBox.down ? "#d0d0d0"
                                          : (typeComboBox.hovered ? AppTheme.comboBoxBackground : "#e8e8e8")
                                    border.color: AppTheme.comboBoxBorder
                                    border.width: 1
                                }

                                contentItem: Text {
                                    text: typeComboBox.currentText
                                    color: "#333333"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: 13
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
                            text: detectService.busy ? qsTr("识别中...") : qsTr("开始识别")
                            enabled: !detectService.busy && root.selectedImageUrl !== ""
                            onClicked: detectService.detect(root.selectedImageUrl, root.recognitionType)

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

                    Item {
                        id: resultImageArea
                        anchors.top: rightPanel.top
                        anchors.left: rightPanel.left
                        anchors.right: rightPanel.right
                        height: Math.max(0, rightPanel.height * 2 / 3 - 8)

                        Image {
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectFit
                            source: detectService.resultImageUrl
                            mipmap: true
                        }

                        Label {
                            anchors.centerIn: parent
                            text: qsTr("识别结果将在此显示")
                            color: "#999999"
                            font.pixelSize: 14
                            visible: !detectService.busy && detectService.resultImageUrl === ""
                        }

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: resultBusyIndicator.top
                            anchors.bottomMargin: 12
                            text: qsTr("正在识别，请稍候...")
                            color: "#666666"
                            font.pixelSize: 14
                            visible: detectService.busy
                        }

                        BusyIndicator {
                            id: resultBusyIndicator
                            anchors.centerIn: parent
                            running: detectService.busy
                            visible: detectService.busy
                        }
                    }

                    Item {
                        id: resultBlock
                        anchors.left: rightPanel.left
                        anchors.right: rightPanel.right
                        anchors.top: resultImageArea.bottom
                        anchors.topMargin: 8
                        anchors.bottom: rightPanel.bottom
                        anchors.bottomMargin: controlBottomMargin
                        clip: true

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16
                            spacing: 8

                            Label {
                                Layout.fillWidth: true
                                text: detectService.statusMessage
                                font.pixelSize: 13
                                font.bold: true
                                color: detectService.errorMessage !== "" ? "#d9534f" : "#333333"
                                wrapMode: Text.WordWrap
                                horizontalAlignment: Text.AlignHCenter
                                visible: detectService.statusMessage !== ""
                            }

                            ScrollView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                visible: detectService.textNumber > 0
                                clip: true

                                Column {
                                    width: parent.width
                                    spacing: 0

                                    Repeater {
                                        model: root.tableRows

                                        delegate: Rectangle {
                                            width: resultBlock.width - 32
                                            height: Math.max(34, valueText.implicitHeight + 14)
                                            color: index % 2 === 0 ? "#ffffff" : "#f7f7f7"
                                            border.color: "#e0e0e0"
                                            border.width: 1

                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.margins: 8
                                                spacing: 12

                                                Text {
                                                    text: modelData.label
                                                    font.pixelSize: 12
                                                    color: "#666666"
                                                    Layout.preferredWidth: 90
                                                    elide: Text.ElideRight
                                                }

                                                Text {
                                                    id: valueText
                                                    text: modelData.value || qsTr("未识别")
                                                    font.pixelSize: 13
                                                    font.bold: true
                                                    color: modelData.value ? "#222222" : "#999999"
                                                    Layout.fillWidth: true
                                                    wrapMode: Text.WordWrap
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
        }
    }

    function driverLicenseRows() {
        return [
            { "label": qsTr("姓名"), "value": detectService.licenseInfo.name || "" },
            { "label": qsTr("性别"), "value": detectService.licenseInfo.gender || "" },
            { "label": qsTr("国籍"), "value": detectService.licenseInfo.nationality || "" },
            { "label": qsTr("证号"), "value": detectService.licenseInfo.idno || "" },
            { "label": qsTr("住址"), "value": detectService.licenseInfo.address || "" },
            { "label": qsTr("准驾车型"), "value": detectService.licenseInfo.type || "" },
            { "label": qsTr("初次领证日期"), "value": detectService.licenseInfo.first_issue_date || "" }
        ]
    }

    function idCardRows() {
        return [
            { "label": qsTr("姓名"), "value": detectService.licenseInfo.name || "" },
            { "label": qsTr("性别"), "value": detectService.licenseInfo.gender || "" },
            { "label": qsTr("民族"), "value": detectService.licenseInfo.nation || "" },
            { "label": qsTr("出生日期"), "value": detectService.licenseInfo.birth_date || "" },
            { "label": qsTr("住址"), "value": detectService.licenseInfo.address || "" },
            { "label": qsTr("公民身份号码"), "value": detectService.licenseInfo.idno || "" }
        ]
    }
}
