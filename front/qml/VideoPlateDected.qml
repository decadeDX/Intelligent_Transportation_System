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

    VideoPlateDetectService {
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
                                detectService.detect(root.selectedVideoUrl, realtimeCheckBox.checked)
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

                // ==================== 右栏：结果视频 + 车牌列表 ====================
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

                        // 车牌列表
                        ScrollView {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            height: Math.min(120, detectService.plateList.length * 40 + 8)
                            visible: detectService.plateList.length > 0
                            clip: true

                            Column {
                                width: parent.width
                                spacing: 4

                                Repeater {
                                    model: detectService.plateList

                                    delegate: Rectangle {
                                        width: rightPanel.width - 20
                                        height: 36; radius: 4
                                        color: "#f9f9f9"
                                        border.color: "#e0e0e0"; border.width: 1

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8; spacing: 12

                                            Text {
                                                text: modelData.plateno || ""
                                                font.pixelSize: 15; font.bold: true
                                                color: "#222222"
                                            }

                                            Rectangle {
                                                width: plateColorLabel.implicitWidth + 12
                                                height: 22; radius: 3
                                                color: _plateColorBg(modelData.platecolor || "")

                                                Text {
                                                    id: plateColorLabel
                                                    anchors.centerIn: parent
                                                    text: modelData.platecolor || ""
                                                    font.pixelSize: 11; color: "#ffffff"
                                                }
                                            }

                                            Text {
                                                text: modelData.city || ""
                                                font.pixelSize: 12; color: "#666666"
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
