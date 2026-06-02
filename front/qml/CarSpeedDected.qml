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

    CarSpeedDetectService {
        id: detectService

        onFrameDetected: function(frameIndex, frameUrl) {
            resultFrameImage.source = frameUrl
        }

        onDetectFinished: function(success) {
            if (!success) return
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
        if (sourceVideoAtEnd) sourceVideo.position = 0
        sourceVideo.play()
    }

    function playResultVideo() {
        if (resultVideoAtEnd) resultVideo.position = 0
        resultVideo.play()
    }

    function clearResultVideo() {
        resultVideo.stop(); resultVideo.source = ""; resultVideo.clearOutput()
    }

    function clearResultDisplay() {
        root.clearResultVideo(); resultFrameImage.source = ""
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
                anchors.fill: parent; spacing: 0

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
                            source: ""; autoPlay: false; loops: 1
                            endOfStreamPolicy: VideoOutput.KeepLastFrame
                        }

                        Label {
                            anchors.centerIn: parent
                            text: qsTr("请上传待检测视频")
                            color: "#999999"; font.pixelSize: 14
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
                        spacing: 12; height: 32

                        Button {
                            id: playSourceBtn
                            width: 90; height: 32; text: qsTr("播放")
                            enabled: root.hasSourceVideo && !detectService.busy
                                     && sourceVideo.playbackState !== MediaPlayer.PlayingState
                            onClicked: root.playSourceVideo()
                            background: Rectangle {
                                implicitWidth: 90; implicitHeight: 32; radius: 4
                                color: playSourceBtn.down ? "#455A64" : (playSourceBtn.hovered ? "#607D8B" : "#546E7A")
                                opacity: playSourceBtn.enabled ? 1.0 : 0.5
                            }
                            contentItem: Text {
                                text: playSourceBtn.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }

                        Button {
                            id: pauseSourceBtn
                            width: 90; height: 32; text: qsTr("暂停")
                            enabled: root.hasSourceVideo && !detectService.busy
                                     && sourceVideo.playbackState === MediaPlayer.PlayingState
                            onClicked: sourceVideo.pause()
                            background: Rectangle {
                                implicitWidth: 90; implicitHeight: 32; radius: 4
                                color: pauseSourceBtn.down ? "#455A64" : (pauseSourceBtn.hovered ? "#607D8B" : "#546E7A")
                                opacity: pauseSourceBtn.enabled ? 1.0 : 0.5
                            }
                            contentItem: Text {
                                text: pauseSourceBtn.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }

                        Button {
                            id: stopSourceBtn
                            width: 90; height: 32; text: qsTr("停止")
                            enabled: root.hasSourceVideo && !detectService.busy
                                     && (sourceVideo.playbackState === MediaPlayer.PlayingState
                                         || sourceVideo.playbackState === MediaPlayer.PausedState
                                         || root.sourceVideoAtEnd)
                            onClicked: { sourceVideo.stop(); sourceVideo.position = 0 }
                            background: Rectangle {
                                implicitWidth: 90; implicitHeight: 32; radius: 4
                                color: stopSourceBtn.down ? "#455A64" : (stopSourceBtn.hovered ? "#607D8B" : "#546E7A")
                                opacity: stopSourceBtn.enabled ? 1.0 : 0.5
                            }
                            contentItem: Text {
                                text: stopSourceBtn.text; color: "#ffffff"
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
                        width: leftPanel.width; spacing: controlSpacing

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

                        // 标定参数
                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 16

                            ColumnLayout {
                                spacing: 2
                                Label { text: qsTr("检测间隔(帧)"); font.pixelSize: 11 }
                                SpinBox {
                                    id: frameIntervalSpin
                                    from: 1; to: 30; value: 1
                                    Layout.preferredWidth: 80
                                    enabled: !detectService.busy
                                }
                            }

                            ColumnLayout {
                                spacing: 2
                                Label { text: qsTr("米/像素"); font.pixelSize: 11 }
                                TextField {
                                    id: mppField
                                    text: "0.1"
                                    Layout.preferredWidth: 80
                                    enabled: !detectService.busy
                                    validator: DoubleValidator { bottom: 0.001; top: 10.0; decimals: 6 }
                                    font.pixelSize: 12
                                }
                            }

                            ColumnLayout {
                                spacing: 2
                                Label { text: qsTr("参考距离(米)"); font.pixelSize: 11 }
                                TextField {
                                    id: refDistField
                                    text: "0"
                                    Layout.preferredWidth: 80
                                    enabled: !detectService.busy
                                    validator: DoubleValidator { bottom: 0; top: 1000; decimals: 2 }
                                    font.pixelSize: 12
                                }
                            }

                            ColumnLayout {
                                spacing: 2
                                Label { text: qsTr("参考像素"); font.pixelSize: 11 }
                                TextField {
                                    id: refPxField
                                    text: "0"
                                    Layout.preferredWidth: 80
                                    enabled: !detectService.busy
                                    validator: DoubleValidator { bottom: 0; top: 10000; decimals: 2 }
                                    font.pixelSize: 12
                                }
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
                            text: detectService.busy ? qsTr("测速中...") : qsTr("开始测速")
                            enabled: !detectService.busy && root.selectedVideoUrl != "" && root.sourceVideoReady
                            onClicked: {
                                sourceVideo.pause()
                                root.clearResultDisplay()
                                detectService.detect(
                                    root.selectedVideoUrl,
                                    frameIntervalSpin.value,
                                    parseFloat(mppField.text) || 0.1,
                                    parseFloat(refDistField.text) || 0,
                                    parseFloat(refPxField.text) || 0
                                )
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

                // ==================== 右栏：结果视频 + 速度列表 ====================
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
                            source: ""; asynchronous: false; cache: false
                            visible: root.isRealtimeMode && root.hasResultFrame
                        }

                        Video {
                            id: resultVideo
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                            source: ""; autoPlay: false; loops: 1
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
                            anchors.bottom: resultBusyIndicator.top; anchors.bottomMargin: 12
                            text: detectService.statusMessage
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
                                id: playResultBtn
                                width: 90; height: 32; text: qsTr("播放")
                                enabled: root.hasResultVideo && resultVideo.playbackState !== MediaPlayer.PlayingState
                                onClicked: root.playResultVideo()
                                background: Rectangle {
                                    implicitWidth: 90; implicitHeight: 32; radius: 4
                                    color: playResultBtn.down ? "#455A64" : (playResultBtn.hovered ? "#607D8B" : "#546E7A")
                                    opacity: playResultBtn.enabled ? 1.0 : 0.5
                                }
                                contentItem: Text {
                                    text: playResultBtn.text; color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                                }
                            }

                            Button {
                                id: pauseResultBtn
                                width: 90; height: 32; text: qsTr("暂停")
                                enabled: root.hasResultVideo && resultVideo.playbackState === MediaPlayer.PlayingState
                                onClicked: resultVideo.pause()
                                background: Rectangle {
                                    implicitWidth: 90; implicitHeight: 32; radius: 4
                                    color: pauseResultBtn.down ? "#455A64" : (pauseResultBtn.hovered ? "#607D8B" : "#546E7A")
                                    opacity: pauseResultBtn.enabled ? 1.0 : 0.5
                                }
                                contentItem: Text {
                                    text: pauseResultBtn.text; color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                                }
                            }

                            Button {
                                id: stopResultBtn
                                width: 90; height: 32; text: qsTr("停止")
                                enabled: root.hasResultVideo
                                         && (resultVideo.playbackState === MediaPlayer.PlayingState
                                             || resultVideo.playbackState === MediaPlayer.PausedState
                                             || root.resultVideoAtEnd)
                                onClicked: { resultVideo.stop(); resultVideo.position = 0 }
                                background: Rectangle {
                                    implicitWidth: 90; implicitHeight: 32; radius: 4
                                    color: stopResultBtn.down ? "#455A64" : (stopResultBtn.hovered ? "#607D8B" : "#546E7A")
                                    opacity: stopResultBtn.enabled ? 1.0 : 0.5
                                }
                                contentItem: Text {
                                    text: stopResultBtn.text; color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                                }
                            }
                        }

                        // 测速摘要
                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 20
                            visible: detectService.speedList.length > 0

                            Label {
                                text: qsTr("最高车速: ") + detectService.maxSpeedKmh.toFixed(1) + " km/h"
                                font.pixelSize: 14; font.bold: true; color: "#d9534f"
                            }
                            Label {
                                text: qsTr("可靠车辆: ") + detectService.reliableVehicleCount + qsTr(" 辆")
                                font.pixelSize: 14; color: "#333333"
                            }
                        }

                        // 速度列表
                        ScrollView {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            height: Math.min(160, detectService.speedList.length * 40 + 8)
                            visible: detectService.speedList.length > 0
                            clip: true

                            Column {
                                width: parent.width; spacing: 4

                                Repeater {
                                    model: detectService.speedList

                                    delegate: Rectangle {
                                        width: rightPanel.width - 20; height: 36; radius: 4
                                        color: modelData.reliable ? "#f0f8f0" : "#fff8f0"
                                        border.color: modelData.reliable ? "#c8e6c9" : "#ffe0b2"
                                        border.width: 1

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8; spacing: 12

                                            Text {
                                                text: "ID:" + (modelData.track_id || "")
                                                font.pixelSize: 13; color: "#555555"
                                                Layout.preferredWidth: 50
                                            }

                                            Text {
                                                text: _classNameZh(modelData.class_name || "")
                                                font.pixelSize: 13; color: "#333333"
                                                Layout.preferredWidth: 50
                                            }

                                            Text {
                                                text: (modelData.speed_kmh || 0).toFixed(1) + " km/h"
                                                font.pixelSize: 15; font.bold: true
                                                color: modelData.reliable ? "#2E7D32" : "#E65100"
                                            }

                                            Rectangle {
                                                width: reliableLabel.implicitWidth + 10; height: 20; radius: 3
                                                color: modelData.reliable ? "#4CAF50" : "#FF9800"
                                                visible: modelData.reliable !== undefined
                                                Text {
                                                    id: reliableLabel
                                                    anchors.centerIn: parent
                                                    text: modelData.reliable ? qsTr("可信") : qsTr("待确认")
                                                    font.pixelSize: 10; color: "#ffffff"
                                                }
                                            }

                                            Item { Layout.fillWidth: true }
                                        }
                                    }
                                }
                            }
                        }

                        // 系统播放器
                        Button {
                            id: sysPlayerBtn
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 160; height: 30
                            text: qsTr("使用系统播放器播放")
                            enabled: !detectService.busy && detectService.resultVideoUrl !== ""
                            onClicked: detectService.openResultVideoWithSystemPlayer()
                            background: Rectangle {
                                implicitWidth: 160; implicitHeight: 30; radius: 4
                                color: sysPlayerBtn.down ? AppTheme.detectButtonPressed
                                      : (sysPlayerBtn.hovered ? AppTheme.detectButtonHover : AppTheme.detectButtonNormal)
                                opacity: sysPlayerBtn.enabled ? 1.0 : 0.6
                            }
                            contentItem: Text {
                                text: sysPlayerBtn.text; color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
                            }
                        }
                    }
                }
            }
        }
    }

    function _classNameZh(name) {
        switch (name) {
            case "car": return qsTr("轿车")
            case "motorcycle": return qsTr("摩托")
            case "bus": return qsTr("巴士")
            case "truck": return qsTr("卡车")
            default: return name
        }
    }
}
