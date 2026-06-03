/**
 * @file LaneDetectService.h
 * @brief 视频车道检测业务服务类（供 QML 调用）
 *
 * 调用 /lineVideoDetected（NDJSON 逐帧流式）。
 */

#ifndef LANEDETECTSERVICE_H
#define LANEDETECTSERVICE_H

#include <QAtomicInt>
#include <QImage>
#include <QJsonObject>
#include <QObject>
#include <QUrl>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;
class StreamFrameImageProvider;

class LaneDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultVideoUrl READ resultVideoUrl NOTIFY resultVideoUrlChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(QString rawJsonText READ rawJsonText NOTIFY rawJsonTextChanged)

public:
    explicit LaneDetectService(QObject *parent = nullptr);
    ~LaneDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultVideoUrl() const;
    QString statusMessage() const;
    QString rawJsonText() const;

    Q_INVOKABLE void detect(const QUrl &sourceVideoUrl);
    Q_INVOKABLE QUrl resolveBackendResourceUrl(const QString &relativePath) const;
    Q_INVOKABLE bool openResultVideoWithSystemPlayer();
    Q_INVOKABLE void cancelDetect();
    Q_INVOKABLE void resetForCleanup();
    Q_INVOKABLE void clearResultMedia();

    static void setFrameImageProvider(StreamFrameImageProvider *provider);

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultVideoUrlChanged();
    void statusMessageChanged();
    void rawJsonTextChanged();
    void frameDetected(int frameIndex, const QString &frameImageUrl);
    void detectFinished(bool success);

private:
    struct UploadContext {
        QString destPath;
    };

    QString resolveBackendRoot() const;
    bool prepareUpload(const QUrl &sourceVideoUrl, UploadContext *ctx);

    void setBusy(bool busy);
    void setErrorMessage(const QString &message);
    void setResultVideoUrl(const QString &url);
    void setStatusMessage(const QString &message);
    void setRawJsonText(const QString &text);
    void setRawJsonFromObject(const QJsonObject &object);
    void cancelActiveRequest();
    void startStreamDetect(const UploadContext &ctx);
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
    QString m_errorMessage;
    QString m_resultVideoUrl;
    QString m_statusMessage;
    QString m_rawJsonText;
    int m_streamTotalFrames = 0;
    int m_statusUpdateCounter = 0;
};

#endif // LANEDETECTSERVICE_H
