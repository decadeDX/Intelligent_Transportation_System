#ifndef VIDEOPLATEDETECTSERVICE_H
#define VIDEOPLATEDETECTSERVICE_H

#include <QAtomicInt>
#include <QImage>
#include <QObject>
#include <QUrl>
#include <QVariantList>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;
class StreamFrameImageProvider;

/// 视频车牌检测服务：封装 /plateVideoDetected 与 /plateVideoDetectedWithFrame
class VideoPlateDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(bool realtimeDetect READ realtimeDetect NOTIFY realtimeDetectChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultVideoUrl READ resultVideoUrl NOTIFY resultVideoUrlChanged)
    Q_PROPERTY(int detectionCount READ detectionCount NOTIFY detectionCountChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(QVariantList plateList READ plateList NOTIFY plateListChanged)

public:
    explicit VideoPlateDetectService(QObject *parent = nullptr);
    ~VideoPlateDetectService() override;

    bool busy() const;
    bool realtimeDetect() const;
    QString errorMessage() const;
    QString resultVideoUrl() const;
    int detectionCount() const;
    QString statusMessage() const;
    QVariantList plateList() const;

    /// 发起视频车牌检测，只需视频路径和是否实时模式
    Q_INVOKABLE void detect(const QUrl &sourceVideoUrl, bool realtimeDetect = false);
    Q_INVOKABLE bool openResultVideoWithSystemPlayer();
    Q_INVOKABLE void cancelDetect();

    static void setFrameImageProvider(StreamFrameImageProvider *provider);

signals:
    void busyChanged();
    void realtimeDetectChanged();
    void errorMessageChanged();
    void resultVideoUrlChanged();
    void detectionCountChanged();
    void statusMessageChanged();
    void plateListChanged();
    void frameDetected(int frameIndex, const QString &frameImageUrl);
    void detectFinished(bool success);

private:
    QString resolveBackendRoot() const;
    QString toLocalFileUrl(const QString &relativePath) const;
    bool prepareUpload(const QUrl &sourceVideoUrl, QString *destPath);

    void setBusy(bool v);
    void setRealtimeDetect(bool v);
    void setErrorMessage(const QString &v);
    void setResultVideoUrl(const QString &v);
    void setDetectionCount(int v);
    void setStatusMessage(const QString &v);
    void setPlateList(const QVariantList &v);
    void cancelActiveRequest();
    void startBatchDetect(const QString &destPath);
    void startStreamDetect(const QString &destPath);
    void handleBatchReply(QNetworkReply *reply);
    void appendStreamData(const QByteArray &chunk);
    void handleStreamLine(const QByteArray &line);
    void finishDetectFailed(const QString &message);
    void finishDetectSuccess();
    void publishFrame(int frameIndex, const QImage &image);
    void scheduleFrameDecode(QByteArray line);

    static StreamFrameImageProvider *s_frameImageProvider;

    QNetworkAccessManager *m_networkManager = nullptr;
    QNetworkReply *m_activeReply = nullptr;
    QByteArray m_streamBuffer;
    QAtomicInt m_decodeJobId{0};
    int m_lastDisplayedFrameIndex = -1;
    bool m_busy = false;
    bool m_realtimeDetect = false;
    QString m_errorMessage;
    QString m_resultVideoUrl;
    int m_detectionCount = 0;
    QString m_statusMessage;
    QVariantList m_plateList;
    int m_streamTotalFrames = 0;
    int m_streamFps = 25;
    int m_statusUpdateCounter = 0;
};

#endif // VIDEOPLATEDETECTSERVICE_H
