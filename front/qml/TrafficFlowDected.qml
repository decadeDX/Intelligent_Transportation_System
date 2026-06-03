import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtMultimedia
import front

Item {
    id: root

    readonly property real containerMarginRatio: 0.01
    readonly property int controlSpacing: 8
    readonly property int controlBottomMargin: 24

    property url selectedVideoUrl: ""
    property int numLanes: laneSpinBox.value

    readonly property bool hasResultVideo: resultVideo.source !== ""
            && resultVideo.error === MediaPlayer.NoError

    readonly property bool hasResultFrame: resultFrameImage.source !== ""

    readonly property bool isRealtimeMode: realtimeCheckBox.checked

    readonly property bool hasResultContent: root.isRealtimeMode
            ? root.hasResultFrame
            : root.hasResultVideo

    StackLayout.onIsCurrentItemChanged: {
        if (!StackLayout.isCurrentItem)
            root.releasePlayback()
    }

    function releasePlayback() {
        sourceVideo.stop()
        resultVideo.stop()
        if (detectService.busy)
            detectService.cancelDetect()
    }

    TrafficFlowDetectService {
        id: detectService

        onFrameDetected: function(frameIndex, frameUrl) {
            resultFrameImage.source = frameUrl
        }

        onDetectFinished: function(success) {
            if (!success)
                return
            if (root.isRealtimeMode)
                resultFrameImage.source = ""
            resultVideo.source = detectService.resultVideoUrl
            Qt.callLater(root.playResultVideo)
        }
    }

    readonly property bool hasSourceVideo: sourceVideo.source !== ""
            && sourceVideo.error === MediaPlayer.NoError

    readonly property bool sourceVideoReady: hasSourceVideo
            && (sourceVideo.hasVideo || sourceVideo.duration > 0 || sourceVideo.seekable)

    readonly property bool sourceVideoAtEnd: sourceVideo.duration > 0
            && sourceVideo.position >= sourceVideo.duration - 100

    readonly property bool resultVideoAtEnd: resultVideo.duration > 0
            && resultVideo.position >= resultVideo.duration - 100

    function playSourceVideo() {
        if (sourceVideoAtEnd)
            sourceVideo.position = 0
        sourceVideo.play()
    }

    function playResultVideo() {
        if (resultVideoAtEnd)
            resultVideo.position = 0
        resultVideo.play()
    }

    function clearResultVideo() {
        resultVideo.stop()
        resultVideo.source = ""
        resultVideo.clearOutput()
    }

    function clearResultDisplay() {
        root.clearResultVideo()
        resultFrameImage.source = ""
    }

    FileDialog {
        id: videoFileDialog
        title: qsTr("选择视频")
        nameFilters: [qsTr("视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.webm)")]
        onAccepted: {
            root.selectedVideoUrl = selectedFile
            sourceVideo.source = selectedFile
            root.clearResultDisplay()
            root.playSourceVideo()
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

                // ==================== 左栏：原视频 + 控件 ====================
                Item {
                    id: leftPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    Item {
                        id: videoArea
                        anchors.top: leftPanel.top
                        anchors.left: leftPanel.left
                        anchors.right: leftPanel.right
                        anchors.bottom: playbackControlsRow.top
                        anchors.bottomMargin: 8

                        Video {
                            id: sourceVideo
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                            source: ""
                            autoPlay: false
                            loops: 1
                            endOfStreamPolicy: VideoOutput.KeepLastFrame
                        }

                        Label {
                            anchors.centerIn: parent
                            text: qsTr("请上传待检测视频")
                            color: "#999999"
                            font.pixelSize: 14
                            visible: !root.hasSourceVideo
                        }
                    }

                    CheckBox {
                        id: realtimeCheckBox
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        anchors.bottom: controlsBlock.top
                        anchors.bottomMargin: 8
                        text: qsTr("实时检测")
                        enabled: !detectService.busy
                    }

                    Row {
                        id: playbackControlsRow
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        anchors.bottom: realtimeCheckBox.top
                        anchors.bottomMargin: 8
                        spacing: 12
                        height: 32

                        Button {
                            id: playButton
                            width: 90; height: 32
                            text: qsTr("播放")
                            enabled: root.hasSourceVideo && (!detectService.busy || root.isRealtimeMode)
                                     && sourceVideo.playbackState !== MediaPlayer.PlayingState
                            onClicked: root.playSourceVideo()

                            background: Rectangle {
                                implicitWidth: 90; implicitHeight: 32; radius: 4
                                color: playButton.down ? "#455A64"
                                      : (playButton.hovered ? "#607D8B" : "#546E7A")
                                opacity: playButton.enabled ? 1.0 : 0.5
                            }
                            contentItem: Text {
                                text: playButton.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }

                        Button {
                            id: pauseButton
                            width: 90; height: 32
                            text: qsTr("暂停")
                            enabled: root.hasSourceVideo && (!detectService.busy || root.isRealtimeMode)
                                     && sourceVideo.playbackState === MediaPlayer.PlayingState
                            onClicked: sourceVideo.pause()

                            background: Rectangle {
                                implicitWidth: 90; implicitHeight: 32; radius: 4
                                color: pauseButton.down ? "#455A64"
                                      : (pauseButton.hovered ? "#607D8B" : "#546E7A")
                                opacity: pauseButton.enabled ? 1.0 : 0.5
                            }
                            contentItem: Text {
                                text: pauseButton.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }

                        Button {
                            id: stopButton
                            width: 90; height: 32
                            text: qsTr("停止")
                            enabled: root.hasSourceVideo && (!detectService.busy || root.isRealtimeMode)
                                     && (sourceVideo.playbackState === MediaPlayer.PlayingState
                                         || sourceVideo.playbackState === MediaPlayer.PausedState
                                         || root.sourceVideoAtEnd)
                            onClicked: { sourceVideo.stop(); sourceVideo.position = 0 }

                            background: Rectangle {
                                implicitWidth: 90; implicitHeight: 32; radius: 4
                                color: stopButton.down ? "#455A64"
                                      : (stopButton.hovered ? "#607D8B" : "#546E7A")
                                opacity: stopButton.enabled ? 1.0 : 0.5
                            }
                            contentItem: Text {
                                text: stopButton.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }
                    }

                    ColumnLayout {
                        id: controlsBlock
                        anchors.bottom: leftPanel.bottom
                        anchors.bottomMargin: controlBottomMargin
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        width: leftPanel.width
                        spacing: controlSpacing

                        // 车道数设置
                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 8

                            Label {
                                text: qsTr("车道数：")
                                font.pixelSize: 13; color: "#555555"
                            }

                            SpinBox {
                                id: laneSpinBox
                                from: 1; to: 8
                                value: 2
                                editable: true
                                enabled: !detectService.busy

                                contentItem: TextInput {
                                    text: laneSpinBox.value
                                    font.pixelSize: 13
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "#333333"
                                    readOnly: !laneSpinBox.editable
                                    validator: laneSpinBox.validator
                                    inputMethodHints: Qt.ImhDigitsOnly
                                }
                            }
                        }

                        Button {
                            id: uploadButton
                            Layout.alignment: Qt.AlignHCenter
                            text: qsTr("上传视频")
                            enabled: !detectService.busy
                            onClicked: videoFileDialog.open()

                            background: Rectangle {
                                implicitWidth: 110; implicitHeight: 30; radius: 4
                                color: uploadButton.down ? AppTheme.uploadButtonPressed
                                      : (uploadButton.hovered ? AppTheme.uploadButtonHover : AppTheme.uploadButtonNormal)
                            }
                            contentItem: Text {
                                text: uploadButton.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }

                        Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: detectService.errorMessage
                            font.pixelSize: 12; color: "#d9534f"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            Layout.maximumWidth: leftPanel.width - 40
                            visible: detectService.errorMessage !== ""
                        }

                        Button {
                            id: detectButton
                            Layout.alignment: Qt.AlignHCenter
                            text: detectService.busy ? qsTr("检测中...") : qsTr("开始检测")
                            enabled: !detectService.busy
                                     && root.selectedVideoUrl !== ""
                                     && root.sourceVideoReady
                            onClicked: {
                                root.clearResultDisplay()
                                if (realtimeCheckBox.checked) {
                                    sourceVideo.position = 0
                                    sourceVideo.play()
                                } else {
                                    sourceVideo.pause()
                                }
                                detectService.detect(root.selectedVideoUrl, laneSpinBox.value, realtimeCheckBox.checked)
                            }

                            background: Rectangle {
                                implicitWidth: 110; implicitHeight: 30; radius: 4
                                color: detectButton.down ? AppTheme.detectButtonPressed
                                      : (detectButton.hovered ? AppTheme.detectButtonHover : AppTheme.detectButtonNormal)
                                opacity: detectButton.enabled ? 1.0 : 0.6
                            }
                            contentItem: Text {
                                text: detectButton.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }
                    }
                }

                // ==================== 分隔线 ====================
                Rectangle {
                    width: 1; height: contentContainer.height
                    color: AppTheme.dividerColor
                }

                // ==================== 右栏：结果视频 + 车流量统计 ====================
                Item {
                    id: rightPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    Item {
                        id: resultVideoArea
                        anchors.top: rightPanel.top
                        anchors.left: rightPanel.left
                        anchors.right: rightPanel.right
                        anchors.bottom: resultStatusBlock.top
                        anchors.bottomMargin: 8

                        Image {
                            id: resultFrameImage
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectFit
                            source: ""
                            asynchronous: false; cache: false
                            visible: root.isRealtimeMode && root.hasResultFrame
                        }

                        Video {
                            id: resultVideo
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                            source: ""
                            autoPlay: false; loops: 1
                            endOfStreamPolicy: VideoOutput.KeepLastFrame
                            visible: root.hasResultVideo && !detectService.busy
                        }

                        Label {
                            anchors.centerIn: parent
                            text: qsTr("检测结果将在此显示")
                            color: "#999999"; font.pixelSize: 14
                            visible: !root.hasResultContent && !detectService.busy
                        }

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: resultBusyIndicator.top
                            anchors.bottomMargin: 12
                            text: root.isRealtimeMode
                                  ? detectService.statusMessage
                                  : qsTr("正在检测，请稍候...")
                            color: "#666666"; font.pixelSize: 14
                            visible: detectService.busy && !root.hasResultFrame
                            horizontalAlignment: Text.AlignHCenter
                            width: parent.width - 40; wrapMode: Text.WordWrap
                        }

                        BusyIndicator {
                            id: resultBusyIndicator
                            anchors.centerIn: parent
                            running: detectService.busy && !root.isRealtimeMode
                            visible: detectService.busy && !root.isRealtimeMode
                        }
                    }

                    Column {
                        id: resultStatusBlock
                        anchors.left: rightPanel.left
                        anchors.right: rightPanel.right
                        anchors.bottom: rightPanel.bottom
                        anchors.bottomMargin: controlBottomMargin
                        spacing: 8

                        // 结果视频播放控制
                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 12; height: 32

                            Button {
                                id: resultPlayButton
                                width: 90; height: 32
                                text: qsTr("播放")
                                enabled: root.hasResultVideo
                                         && resultVideo.playbackState !== MediaPlayer.PlayingState
                                onClicked: root.playResultVideo()

                                background: Rectangle {
                                    implicitWidth: 90; implicitHeight: 32; radius: 4
                                    color: resultPlayButton.down ? "#455A64"
                                          : (resultPlayButton.hovered ? "#607D8B" : "#546E7A")
                                    opacity: resultPlayButton.enabled ? 1.0 : 0.5
                                }
                                contentItem: Text {
                                    text: resultPlayButton.text; color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                                }
                            }

                            Button {
                                id: resultPauseButton
                                width: 90; height: 32
                                text: qsTr("暂停")
                                enabled: root.hasResultVideo
                                         && resultVideo.playbackState === MediaPlayer.PlayingState
                                onClicked: resultVideo.pause()

                                background: Rectangle {
                                    implicitWidth: 90; implicitHeight: 32; radius: 4
                                    color: resultPauseButton.down ? "#455A64"
                                          : (resultPauseButton.hovered ? "#607D8B" : "#546E7A")
                                    opacity: resultPauseButton.enabled ? 1.0 : 0.5
                                }
                                contentItem: Text {
                                    text: resultPauseButton.text; color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                                }
                            }

                            Button {
                                id: resultStopButton
                                width: 90; height: 32
                                text: qsTr("停止")
                                enabled: root.hasResultVideo
                                         && (resultVideo.playbackState === MediaPlayer.PlayingState
                                             || resultVideo.playbackState === MediaPlayer.PausedState
                                             || root.resultVideoAtEnd)
                                onClicked: { resultVideo.stop(); resultVideo.position = 0 }

                                background: Rectangle {
                                    implicitWidth: 90; implicitHeight: 32; radius: 4
                                    color: resultStopButton.down ? "#455A64"
                                          : (resultStopButton.hovered ? "#607D8B" : "#546E7A")
                                    opacity: resultStopButton.enabled ? 1.0 : 0.5
                                }
                                contentItem: Text {
                                    text: resultStopButton.text; color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                                }
                            }
                        }

                        // 状态信息
                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.width - 40
                            text: detectService.statusMessage
                            font.pixelSize: 13; font.bold: true
                            color: "#333333"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            visible: detectService.statusMessage !== ""
                                     && detectService.statusMessage !== qsTr("正在检测，请稍候...")
                                     && detectService.statusMessage !== qsTr("实时检测中，请稍候...")
                        }

                        // 系统播放器按钮
                        Button {
                            id: openwithSystemPlayerButton
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 160; height: 30
                            text: qsTr("使用系统播放器播放")
                            enabled: !detectService.busy && detectService.resultVideoUrl !== ""
                            onClicked: detectService.openResultVideoWithSystemPlayer()

                            background: Rectangle {
                                implicitWidth: 160; implicitHeight: 30; radius: 4
                                color: openwithSystemPlayerButton.down ? AppTheme.detectButtonPressed
                                      : (openwithSystemPlayerButton.hovered ? AppTheme.detectButtonHover : AppTheme.detectButtonNormal)
                                opacity: openwithSystemPlayerButton.enabled ? 1.0 : 0.6
                            }
                            contentItem: Text {
                                text: openwithSystemPlayerButton.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }

                        // 车流量统计面板
                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: 20
                            anchors.rightMargin: 20
                            spacing: 6
                            visible: detectService.uniqueVehicleCount !== undefined
                                     && detectService.uniqueVehicleCount >= 0

                            // 道路状况标签
                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: roadConditionText.implicitWidth + 24
                                height: 32; radius: 16
                                color: _roadConditionBg(detectService.roadCondition || "")

                                Text {
                                    id: roadConditionText
                                    anchors.centerIn: parent
                                    text: detectService.roadCondition || qsTr("--")
                                    font.pixelSize: 15; font.bold: true
                                    color: "#ffffff"
                                }
                            }

                            // 统计数字
                            RowLayout {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                spacing: 0

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: detectService.uniqueVehicleCount || 0
                                        font.pixelSize: 22; font.bold: true
                                        color: "#333333"
                                    }
                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: qsTr("唯一车辆数")
                                        font.pixelSize: 11; color: "#888888"
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: (detectService.hourlyTrafficRatio || 0).toFixed(0)
                                        font.pixelSize: 22; font.bold: true
                                        color: "#2196F3"
                                    }
                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: qsTr("小时流量(辆/h)")
                                        font.pixelSize: 11; color: "#888888"
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: detectService.numLanes || laneSpinBox.value
                                        font.pixelSize: 22; font.bold: true
                                        color: "#4CAF50"
                                    }
                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: qsTr("车道数")
                                        font.pixelSize: 11; color: "#888888"
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: (detectService.durationSec || 0).toFixed(1) + "s"
                                        font.pixelSize: 22; font.bold: true
                                        color: "#FF9800"
                                    }
                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: qsTr("视频时长")
                                        font.pixelSize: 11; color: "#888888"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    function _roadConditionBg(condition) {
        switch (condition) {
            case "畅通": return "#4CAF50"
            case "正常": return "#FF9800"
            case "拥堵": return "#d9534f"
            default:     return "#757575"
        }
    }
}
