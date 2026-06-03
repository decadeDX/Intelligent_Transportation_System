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
    readonly property int jsonPanelMinHeight: 160

    readonly property string sampleVideoRelativePath: "video/car_line01.mp4"

    property url selectedVideoUrl: ""
    property string sampleVideoLoadError: ""

    readonly property string formattedJsonText: beautifyJson(detectService.rawJsonText)

    function beautifyJson(raw) {
        if (!raw || raw.trim() === "")
            return ""
        try {
            return JSON.stringify(JSON.parse(raw), null, 2)
        } catch (e) {
            return raw
        }
    }

    readonly property bool hasResultVideo: detectService.resultVideoUrl !== ""

    readonly property bool hasResultFrame: resultFrameImage.source !== ""

    readonly property bool showLiveFrame: detectService.busy && root.hasResultFrame

    readonly property bool showResultVideo: root.hasResultVideo
            && !detectService.busy
            && !root.showLiveFrame

    readonly property bool hasResultContent: root.hasResultVideo || root.hasResultFrame

    LaneDetectService {
        id: detectService

        onFrameDetected: function(frameIndex, frameUrl) {
            resultFrameImage.source = frameUrl
        }

        onDetectFinished: function(success) {
            if (!success)
                return
            resultFrameImage.source = ""
            root.scheduleResultVideoPlayback()
        }
    }

    function scheduleResultVideoPlayback() {
        Qt.callLater(function() {
            if (detectService.resultVideoUrl !== "")
                root.playResultVideo()
        })
    }

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

    readonly property bool hasSourceVideo: sourceVideo.source !== ""
            && sourceVideo.error === MediaPlayer.NoError

    readonly property bool sourceVideoReady: hasSourceVideo
            && (sourceVideo.hasVideo || sourceVideo.duration > 0 || sourceVideo.seekable)

    readonly property bool sourceVideoAtEnd: sourceVideo.duration > 0
            && sourceVideo.position >= sourceVideo.duration - 100

    readonly property bool resultVideoAtEnd: resultVideo.duration > 0
            && resultVideo.position >= resultVideo.duration - 100

    function playSourceVideo() {
        if (sourceVideoAtEnd) {
            sourceVideo.position = 0
        }
        sourceVideo.play()
    }

    function playResultVideo() {
        if (resultVideoAtEnd) {
            resultVideo.position = 0
        }
        resultVideo.play()
    }

    function loadSampleVideo() {
        root.sampleVideoLoadError = ""
        const sampleUrl = detectService.resolveBackendResourceUrl(root.sampleVideoRelativePath)
        if (!sampleUrl || sampleUrl.toString() === "") {
            root.sampleVideoLoadError = qsTr("示例视频不存在：%1").arg(root.sampleVideoRelativePath)
            return
        }
        root.selectedVideoUrl = sampleUrl
        sourceVideo.source = sampleUrl
        root.clearResultDisplay()
        root.playSourceVideo()
    }

    function clearResultVideo() {
        resultVideo.stop()
        resultVideo.clearOutput()
        detectService.clearResultMedia()
    }

    function clearResultDisplay() {
        root.clearResultVideo()
        resultFrameImage.source = ""
    }

    function resetForTempCleanup() {
        if (detectService.busy)
            detectService.cancelDetect()
        detectService.resetForCleanup()
        selectedVideoUrl = ""
        sourceVideo.stop()
        sourceVideo.source = ""
        sourceVideo.clearOutput()
        sourceVideo.position = 0
        resultVideo.stop()
        resultVideo.clearOutput()
        resultVideo.position = 0
        resultFrameImage.source = ""
        sampleVideoLoadError = ""
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

                Item {
                    id: leftPanel
                    width: (contentContainer.width - 1) / 2
                    height: contentContainer.height

                    Item {
                        id: videoArea
                        anchors.top: leftPanel.top
                        anchors.left: leftPanel.left
                        anchors.right: leftPanel.right
                        anchors.bottom: sampleVideoLinkRow.top
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

                    Column {
                        id: sampleVideoLinkRow
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        anchors.bottom: playbackControlsRow.top
                        anchors.bottomMargin: 6
                        spacing: 2

                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 4

                            Label {
                                text: qsTr("示例视频：")
                                font.pixelSize: 12
                                color: "#666666"
                            }

                            Label {
                                text: root.sampleVideoRelativePath
                                property bool linkHovered: false
                                font.pixelSize: 12
                                color: linkHovered ? "#1565C0" : "#2196F3"
                                font.underline: true

                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    enabled: !detectService.busy
                                    onClicked: root.loadSampleVideo()
                                    onContainsMouseChanged: parent.linkHovered = containsMouse
                                }
                            }
                        }

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: root.sampleVideoLoadError
                            font.pixelSize: 11
                            color: "#d9534f"
                            visible: root.sampleVideoLoadError !== ""
                        }
                    }

                    Row {
                        id: playbackControlsRow
                        anchors.horizontalCenter: leftPanel.horizontalCenter
                        anchors.bottom: controlsBlock.top
                        anchors.bottomMargin: 8
                        spacing: 12
                        height: 32

                        Button {
                            id: playButton
                            width: 90
                            height: 32
                            text: qsTr("播放")
                            enabled: root.hasSourceVideo && !detectService.busy
                                     && sourceVideo.playbackState !== MediaPlayer.PlayingState
                            onClicked: root.playSourceVideo()

                            background: Rectangle {
                                implicitWidth: 90
                                implicitHeight: 32
                                radius: 4
                                color: playButton.down ? "#455A64"
                                      : (playButton.hovered ? "#607D8B" : "#546E7A")
                                opacity: playButton.enabled ? 1.0 : 0.5
                            }

                            contentItem: Text {
                                text: playButton.text
                                color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 13
                            }
                        }

                        Button {
                            id: pauseButton
                            width: 90
                            height: 32
                            text: qsTr("暂停")
                            enabled: root.hasSourceVideo && !detectService.busy
                                     && sourceVideo.playbackState === MediaPlayer.PlayingState
                            onClicked: sourceVideo.pause()

                            background: Rectangle {
                                implicitWidth: 90
                                implicitHeight: 32
                                radius: 4
                                color: pauseButton.down ? "#455A64"
                                      : (pauseButton.hovered ? "#607D8B" : "#546E7A")
                                opacity: pauseButton.enabled ? 1.0 : 0.5
                            }

                            contentItem: Text {
                                text: pauseButton.text
                                color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 13
                            }
                        }

                        Button {
                            id: stopButton
                            width: 90
                            height: 32
                            text: qsTr("停止")
                            enabled: root.hasSourceVideo && !detectService.busy
                                     && (sourceVideo.playbackState === MediaPlayer.PlayingState
                                         || sourceVideo.playbackState === MediaPlayer.PausedState
                                         || root.sourceVideoAtEnd)
                            onClicked: {
                                sourceVideo.stop()
                                sourceVideo.position = 0
                            }

                            background: Rectangle {
                                implicitWidth: 90
                                implicitHeight: 32
                                radius: 4
                                color: stopButton.down ? "#455A64"
                                      : (stopButton.hovered ? "#607D8B" : "#546E7A")
                                opacity: stopButton.enabled ? 1.0 : 0.5
                            }

                            contentItem: Text {
                                text: stopButton.text
                                color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 13
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
                            text: detectService.busy ? qsTr("检测中...") : qsTr("开始检测")
                            enabled: !detectService.busy
                                     && root.selectedVideoUrl !== ""
                                     && root.sourceVideoReady
                            onClicked: {
                                sourceVideo.pause()
                                root.clearResultDisplay()
                                detectService.detect(root.selectedVideoUrl)
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
                        anchors.bottomMargin: controlBottomMargin
                        spacing: 8

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 100

                            Image {
                                id: resultFrameImage
                                anchors.fill: parent
                                fillMode: Image.PreserveAspectFit
                                source: ""
                                asynchronous: false
                                cache: false
                                visible: root.showLiveFrame
                            }

                            Video {
                                id: resultVideo
                                anchors.fill: parent
                                fillMode: VideoOutput.PreserveAspectFit
                                source: detectService.resultVideoUrl
                                autoPlay: false
                                loops: 1
                                endOfStreamPolicy: VideoOutput.KeepLastFrame
                                visible: root.showResultVideo
                            }

                            Label {
                                anchors.centerIn: parent
                                text: qsTr("检测结果将在此显示")
                                color: "#999999"
                                font.pixelSize: 14
                                visible: !root.hasResultContent && !detectService.busy
                            }

                            Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: resultBusyIndicator.top
                                anchors.bottomMargin: 12
                                text: detectService.statusMessage
                                color: "#666666"
                                font.pixelSize: 14
                                visible: detectService.busy && !root.hasResultFrame
                                horizontalAlignment: Text.AlignHCenter
                                width: parent.width - 40
                                wrapMode: Text.WordWrap
                            }

                            BusyIndicator {
                                id: resultBusyIndicator
                                anchors.centerIn: parent
                                running: detectService.busy && !root.hasResultFrame
                                visible: detectService.busy && !root.hasResultFrame
                            }
                        }

                        Row {
                            id: resultPlaybackControlsRow
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 12
                            height: 32

                            Button {
                                id: resultPlayButton
                                width: 90
                                height: 32
                                text: qsTr("播放")
                                enabled: root.hasResultVideo
                                         && resultVideo.playbackState !== MediaPlayer.PlayingState
                                onClicked: root.playResultVideo()

                                background: Rectangle {
                                    implicitWidth: 90
                                    implicitHeight: 32
                                    radius: 4
                                    color: resultPlayButton.down ? "#455A64"
                                          : (resultPlayButton.hovered ? "#607D8B" : "#546E7A")
                                    opacity: resultPlayButton.enabled ? 1.0 : 0.5
                                }

                                contentItem: Text {
                                    text: resultPlayButton.text
                                    color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: 13
                                }
                            }

                            Button {
                                id: resultPauseButton
                                width: 90
                                height: 32
                                text: qsTr("暂停")
                                enabled: root.hasResultVideo
                                         && resultVideo.playbackState === MediaPlayer.PlayingState
                                onClicked: resultVideo.pause()

                                background: Rectangle {
                                    implicitWidth: 90
                                    implicitHeight: 32
                                    radius: 4
                                    color: resultPauseButton.down ? "#455A64"
                                          : (resultPauseButton.hovered ? "#607D8B" : "#546E7A")
                                    opacity: resultPauseButton.enabled ? 1.0 : 0.5
                                }

                                contentItem: Text {
                                    text: resultPauseButton.text
                                    color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: 13
                                }
                            }

                            Button {
                                id: resultStopButton
                                width: 90
                                height: 32
                                text: qsTr("停止")
                                enabled: root.hasResultVideo
                                         && (resultVideo.playbackState === MediaPlayer.PlayingState
                                             || resultVideo.playbackState === MediaPlayer.PausedState
                                             || root.resultVideoAtEnd)
                                onClicked: {
                                    resultVideo.stop()
                                    resultVideo.position = 0
                                }

                                background: Rectangle {
                                    implicitWidth: 90
                                    implicitHeight: 32
                                    radius: 4
                                    color: resultStopButton.down ? "#455A64"
                                          : (resultStopButton.hovered ? "#607D8B" : "#546E7A")
                                    opacity: resultStopButton.enabled ? 1.0 : 0.5
                                }

                                contentItem: Text {
                                    text: resultStopButton.text
                                    color: "#ffffff"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: 13
                                }
                            }
                        }

                        Label {
                            id: resultStatusLabel
                            Layout.alignment: Qt.AlignHCenter
                            Layout.fillWidth: true
                            text: detectService.statusMessage
                            font.pixelSize: 13
                            font.bold: true
                            color: "#333333"
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            visible: detectService.statusMessage !== ""
                                     && detectService.statusMessage !== qsTr("逐帧检测中，请稍候...")
                        }

                        Button {
                            id: openWithSystemPlayerButton
                            Layout.alignment: Qt.AlignHCenter
                            width: 160
                            height: 30
                            text: qsTr("使用系统播放器播放")
                            enabled: !detectService.busy && detectService.resultVideoUrl !== ""
                            onClicked: detectService.openResultVideoWithSystemPlayer()

                            background: Rectangle {
                                implicitWidth: 160
                                implicitHeight: 30
                                radius: 4
                                color: openWithSystemPlayerButton.down ? AppTheme.detectButtonPressed
                                      : (openWithSystemPlayerButton.hovered ? AppTheme.detectButtonHover : AppTheme.detectButtonNormal)
                                opacity: openWithSystemPlayerButton.enabled ? 1.0 : 0.6
                            }

                            contentItem: Text {
                                text: openWithSystemPlayerButton.text
                                color: "#ffffff"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 13
                            }
                        }

                        Rectangle {
                            id: jsonPanel
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(jsonPanelMinHeight,
                                                             rightPanel.height * 0.28)
                            color: "#f8f9fb"
                            border.color: AppTheme.dividerColor
                            border.width: 1
                            radius: 4

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 6

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    Label {
                                        text: qsTr("接口返回 JSON")
                                        font.pixelSize: 12
                                        font.bold: true
                                        color: "#333333"
                                    }

                                    Item { Layout.fillWidth: true }

                                    Label {
                                        text: root.formattedJsonText !== ""
                                              ? qsTr("已格式化")
                                              : qsTr("等待检测")
                                        font.pixelSize: 11
                                        color: root.formattedJsonText !== "" ? "#5cb85c" : "#999999"
                                    }
                                }

                                ScrollView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    ScrollBar.vertical.policy: ScrollBar.AsNeeded
                                    ScrollBar.horizontal.policy: ScrollBar.AsNeeded

                                    TextArea {
                                        id: jsonTextArea
                                        readOnly: true
                                        selectByMouse: true
                                        wrapMode: TextArea.NoWrap
                                        text: root.formattedJsonText
                                        font.family: "Consolas, Courier New, monospace"
                                        font.pixelSize: 11
                                        color: "#2c3e50"
                                        padding: 8
                                        background: Rectangle {
                                            color: "#ffffff"
                                            border.color: "#e0e4ea"
                                            border.width: 1
                                            radius: 2
                                        }
                                    }
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: qsTr("检测完成后，/lineVideoDetected 接口 done 事件 JSON 将在此展示")
                                    font.pixelSize: 11
                                    color: "#999999"
                                    wrapMode: Text.WordWrap
                                    visible: root.formattedJsonText === ""
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
