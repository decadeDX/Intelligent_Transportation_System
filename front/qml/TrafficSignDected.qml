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
    property url selectedImageUrl: ""
    property string uploadMode: uploadModeComboBox.currentText

    // 视频模式相关
    readonly property bool hasResultVideo: resultVideo.source !== ""
            && resultVideo.error === MediaPlayer.NoError
    readonly property bool hasResultFrame: resultFrameImage.source !== ""
    readonly property bool isRealtimeMode: realtimeCheckBox.checked
    readonly property bool hasVideoResultContent: root.isRealtimeMode
            ? root.hasResultFrame
            : root.hasResultVideo

    // 图片模式相关
    readonly property bool hasResultImage: resultImage.source !== ""
            && resultImage.status === Image.Ready

    // 综合判断
    readonly property bool isVideoMode: root.uploadMode === "视频"
    readonly property bool hasResultContent: root.isVideoMode
            ? root.hasVideoResultContent
            : root.hasResultImage
    property bool hasFinalResult: false
    property int finalSignCount: 0
    property int finalUniqueSignTypes: 0
    property string finalStatusMessage: ""
    property var finalSignList: []

    StackLayout.onIsCurrentItemChanged: {
        if (!StackLayout.isCurrentItem)
            root.releasePlayback()
    }

    function releasePlayback() {
        if (root.isVideoMode) {
            sourceVideo.stop()
            resultVideo.stop()
        }
        if (detectService.busy)
            detectService.cancelDetect()
    }

    TrafficSignDetectService {
        id: detectService

        onFrameDetected: function(frameIndex, frameUrl) {
            resultFrameImage.source = frameUrl
        }

        onDetectFinished: function(success) {
            if (!success)
                return
            root.hasFinalResult = true
            root.finalSignCount = detectService.signCount
            root.finalUniqueSignTypes = detectService.uniqueSignTypes
            root.finalStatusMessage = detectService.statusMessage
            root.finalSignList = detectService.signList
            if (root.isVideoMode) {
                if (root.isRealtimeMode)
                    resultFrameImage.source = ""
                resultVideo.source = detectService.resultVideoUrl
                Qt.callLater(root.playResultVideo)
            } else {
                resultImage.source = detectService.resultImageUrl
            }
        }
    }

    // ==================== 视频模式 state ====================
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
        resultImage.source = ""
        root.hasFinalResult = false
        root.finalSignCount = 0
        root.finalUniqueSignTypes = 0
        root.finalStatusMessage = ""
        root.finalSignList = []
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

    FileDialog {
        id: imageFileDialog
        title: qsTr("选择图片")
        nameFilters: [qsTr("图片文件 (*.png *.jpg *.jpeg *.bmp)")]
        onAccepted: {
            root.selectedImageUrl = selectedFile
            sourceImage.source = selectedFile
            root.clearResultDisplay()
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

                // ==================== 左栏：原视频/图片 + 控件 ====================
                Item {
                    id: leftPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    // 视频显示区域
                    Item {
                        id: videoArea
                        anchors.top: leftPanel.top
                        anchors.left: leftPanel.left
                        anchors.right: leftPanel.right
                        anchors.bottom: playbackControlsRow.top
                        anchors.bottomMargin: 8
                        visible: root.isVideoMode

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

                    // 图片显示区域
                    Item {
                        id: imageArea
                        anchors.top: leftPanel.top
                        anchors.left: leftPanel.left
                        anchors.right: leftPanel.right
                        anchors.bottom: controlsBlock.top
                        anchors.bottomMargin: 20
                        visible: !root.isVideoMode

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

                    // 视频播放控制（仅视频模式）
                    Row {
                        id: playbackControlsRow
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        anchors.bottom: realtimeCheckBox.top
                        anchors.bottomMargin: 8
                        spacing: 12
                        height: 32
                        visible: root.isVideoMode

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

                    // 实时检测复选框（仅视频模式）
                    CheckBox {
                        id: realtimeCheckBox
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        anchors.bottom: controlsBlock.top
                        anchors.bottomMargin: 8
                        text: qsTr("实时检测")
                        enabled: !detectService.busy
                        visible: root.isVideoMode
                    }

                    // 控件区域
                    ColumnLayout {
                        id: controlsBlock
                        anchors.bottom: leftPanel.bottom
                        anchors.bottomMargin: controlBottomMargin
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        width: leftPanel.width
                        spacing: controlSpacing

                        // 上传方式选择
                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 8

                            Label {
                                text: qsTr("上传方式：")
                                font.pixelSize: 13; color: "#555555"
                            }

                            ComboBox {
                                id: uploadModeComboBox
                                model: [qsTr("视频"), qsTr("图片")]
                                currentIndex: 0
                                enabled: !detectService.busy

                                onCurrentTextChanged: {
                                    root.clearResultDisplay()
                                }

                                background: Rectangle {
                                    implicitWidth: 100; implicitHeight: 30; radius: 4
                                    color: uploadModeComboBox.down ? "#d0d0d0"
                                          : (uploadModeComboBox.hovered ? AppTheme.comboBoxBackground : "#e8e8e8")
                                    border.color: AppTheme.comboBoxBorder; border.width: 1
                                }

                                contentItem: Text {
                                    text: uploadModeComboBox.currentText
                                    font.pixelSize: 13; color: "#333333"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 10
                                }

                                delegate: ItemDelegate {
                                    width: uploadModeComboBox.width
                                    contentItem: Text {
                                        text: modelData
                                        font.pixelSize: 13
                                        color: highlighted ? "#2196F3" : "#333333"
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    highlighted: uploadModeComboBox.highlightedIndex === index
                                    background: Rectangle {
                                        radius: 2
                                        color: highlighted ? "#e3f2fd" : "#ffffff"
                                    }
                                }

                                popup: Popup {
                                    y: uploadModeComboBox.height + 2
                                    width: uploadModeComboBox.width
                                    implicitHeight: contentItem.implicitHeight
                                    padding: 1

                                    contentItem: ListView {
                                        clip: true
                                        implicitHeight: contentHeight
                                        model: uploadModeComboBox.popup.visible ? uploadModeComboBox.delegateModel : null
                                        currentIndex: uploadModeComboBox.highlightedIndex
                                        boundsBehavior: Flickable.StopAtBounds
                                    }

                                    background: Rectangle {
                                        radius: 4
                                        color: "#ffffff"
                                        border.color: AppTheme.comboBoxBorder
                                    }
                                }
                            }
                        }

                        Button {
                            id: uploadButton
                            Layout.alignment: Qt.AlignHCenter
                            text: root.isVideoMode ? qsTr("上传视频") : qsTr("上传图片")
                            enabled: !detectService.busy
                            onClicked: {
                                if (root.isVideoMode)
                                    videoFileDialog.open()
                                else
                                    imageFileDialog.open()
                            }

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
                            enabled: !detectService.busy && (root.isVideoMode
                                     ? (root.selectedVideoUrl !== "" && root.sourceVideoReady)
                                     : root.selectedImageUrl !== "")
                            onClicked: {
                                root.clearResultDisplay()
                                if (root.isVideoMode) {
                                    if (realtimeCheckBox.checked) {
                                        sourceVideo.position = 0
                                        sourceVideo.play()
                                    } else {
                                        sourceVideo.pause()
                                    }
                                    detectService.detect(root.selectedVideoUrl, 1)
                                } else {
                                    detectService.detect(root.selectedImageUrl, 0)
                                }
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

                // ==================== 右栏：结果 + 标识列表 ====================
                Item {
                    id: rightPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    Item {
                        id: resultDisplayArea
                        anchors.top: rightPanel.top
                        anchors.left: rightPanel.left
                        anchors.right: rightPanel.right
                        height: Math.max(0, rightPanel.height * 0.75 - 8)

                        // 视频结果框（实时帧）
                        Image {
                            id: resultFrameImage
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectFit
                            source: ""
                            asynchronous: false; cache: false
                            visible: root.isVideoMode && root.isRealtimeMode && root.hasResultFrame
                        }

                        // 视频结果
                        Video {
                            id: resultVideo
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                            source: ""
                            autoPlay: false; loops: 1
                            endOfStreamPolicy: VideoOutput.KeepLastFrame
                            visible: root.isVideoMode && root.hasResultVideo && !detectService.busy
                        }

                        // 图片结果
                        Image {
                            id: resultImage
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectFit
                            source: ""
                            mipmap: true
                            visible: !root.isVideoMode
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
                            text: root.isVideoMode && root.isRealtimeMode
                                  ? detectService.statusMessage
                                  : qsTr("正在检测，请稍候...")
                            color: "#666666"; font.pixelSize: 14
                            visible: detectService.busy && (!root.isVideoMode || !root.hasResultFrame)
                            horizontalAlignment: Text.AlignHCenter
                            width: parent.width - 40; wrapMode: Text.WordWrap
                        }

                        BusyIndicator {
                            id: resultBusyIndicator
                            anchors.centerIn: parent
                            running: detectService.busy && (!root.isVideoMode || !root.isRealtimeMode)
                            visible: detectService.busy && (!root.isVideoMode || !root.isRealtimeMode)
                        }
                    }

                    Column {
                        id: resultStatusBlock
                        anchors.left: rightPanel.left
                        anchors.right: rightPanel.right
                        anchors.top: resultDisplayArea.bottom
                        anchors.topMargin: 8
                        anchors.bottom: rightPanel.bottom
                        anchors.bottomMargin: controlBottomMargin
                        clip: true
                        spacing: 8

                        // 结果视频播放控制（仅视频模式）
                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 12; height: 32
                            visible: root.isVideoMode

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
                            text: root.finalStatusMessage
                            font.pixelSize: 13; font.bold: true
                            color: "#333333"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            visible: root.hasFinalResult && root.finalStatusMessage !== ""
                        }

                        // 系统播放器按钮（仅视频模式）
                        Button {
                            id: openwithSystemPlayerButton
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 160; height: 30
                            text: qsTr("使用系统播放器播放")
                            enabled: !detectService.busy && detectService.resultVideoUrl !== ""
                            onClicked: detectService.openResultVideoWithSystemPlayer()
                            visible: root.isVideoMode

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

                        // 检测统计简要信息
                        RowLayout {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: 20
                            anchors.rightMargin: 20
                            spacing: 0
                            visible: root.hasFinalResult

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: root.finalSignCount || 0
                                    font.pixelSize: 22; font.bold: true
                                    color: "#2196F3"
                                }
                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: qsTr("检测标识数")
                                    font.pixelSize: 11; color: "#888888"
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: root.finalUniqueSignTypes || 0
                                    font.pixelSize: 22; font.bold: true
                                    color: "#4CAF50"
                                }
                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: qsTr("标识种类")
                                    font.pixelSize: 11; color: "#888888"
                                }
                            }
                        }

                        // 标识列表
                        ScrollView {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            height: Math.max(48, resultStatusBlock.height - 130)
                            visible: root.hasFinalResult && root.finalSignList.length > 0
                            clip: true

                            Column {
                                width: parent.width
                                spacing: 4

                                Repeater {
                                    model: root.finalSignList

                                    delegate: Rectangle {
                                        width: rightPanel.width - 20
                                        height: 40; radius: 4
                                        color: "#f9f9f9"
                                        border.color: "#e0e0e0"; border.width: 1

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8; spacing: 10

                                            Rectangle {
                                                width: 26; height: 26; radius: 13
                                                color: _signColor(modelData.class_name || "")

                                                Text {
                                                    anchors.centerIn: parent
                                                    text: (modelData.class_name || "?").substring(0, 1)
                                                    font.pixelSize: 11; font.bold: true
                                                    color: "#ffffff"
                                                }
                                            }

                                            Text {
                                                text: modelData.class_name || qsTr("未知")
                                                font.pixelSize: 14; font.bold: true
                                                color: "#222222"
                                            }

                                            Item { Layout.fillWidth: true }

                                            Text {
                                                text: modelData.count !== undefined
                                                      ? qsTr("%1 次").arg(modelData.count)
                                                      : ((modelData.confidence || 0) * 100).toFixed(1) + "%"
                                                font.pixelSize: 12; color: "#888888"
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

    function _signColor(className) {
        var hash = 0
        for (var i = 0; i < className.length; i++) {
            hash = className.charCodeAt(i) + ((hash << 5) - hash)
        }
        var colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
                      "#1abc9c", "#e67e22", "#2980b9", "#27ae60", "#8e44ad"]
        return colors[Math.abs(hash) % colors.length]
    }
}
