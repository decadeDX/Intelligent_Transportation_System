#ifndef TRAFFICSIGNDETECTSERVICE_H
#define TRAFFICSIGNDETECTSERVICE_H

#include <QAtomicInt>
#include <QImage>
#include <QObject>
#include <QUrl>
#include <QVariantList>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;
class StreamFrameImageProvider;

class TrafficSignDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultVideoUrl READ resultVideoUrl NOTIFY resultVideoUrlChanged)
    Q_PROPERTY(QString resultImageUrl READ resultImageUrl NOTIFY resultImageUrlChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(int signCount READ signCount NOTIFY signCountChanged)
    Q_PROPERTY(int uniqueSignTypes READ uniqueSignTypes NOTIFY uniqueSignTypesChanged)
    Q_PROPERTY(QVariantList signList READ signList NOTIFY signListChanged)

public:
    explicit TrafficSignDetectService(QObject *parent = nullptr);
    ~TrafficSignDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultVideoUrl() const;
    QString resultImageUrl() const;
    QString statusMessage() const;
    int signCount() const;
    int uniqueSignTypes() const;
    QVariantList signList() const;

    Q_INVOKABLE void detect(const QUrl &sourceUrl, int mediaType = 1);
    Q_INVOKABLE bool openResultVideoWithSystemPlayer();
    Q_INVOKABLE void cancelDetect();

    static void setFrameImageProvider(StreamFrameImageProvider *provider);

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultVideoUrlChanged();
    void resultImageUrlChanged();
    void statusMessageChanged();
    void signCountChanged();
    void uniqueSignTypesChanged();
    void signListChanged();
    void frameDetected(int frameIndex, const QString &frameImageUrl);
    void detectFinished(bool success);

private:
    enum class MediaMode {
        Image,
        Video,
    };

    QString resolveBackendRoot() const;
    bool prepareUpload(const QUrl &sourceUrl, QString *destPath);
    void setBusy(bool value);
    void setErrorMessage(const QString &value);
    void setResultVideoUrl(const QString &value);
    void setResultImageUrl(const QString &value);
    void setStatusMessage(const QString &value);
    void setSignCount(int value);
    void setUniqueSignTypes(int value);
    void setSignList(const QVariantList &value);
    void resetResultState();
    void cancelActiveRequest();
    void startImageDetect(const QString &destPath);
    void startVideoDetect(const QString &destPath);
    void handleImageReply(QNetworkReply *reply);
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
    QString m_resultImageUrl;
    QString m_statusMessage;
    int m_signCount = 0;
    int m_uniqueSignTypes = 0;
    QVariantList m_signList;
    MediaMode m_mode = MediaMode::Video;
    int m_streamTotalFrames = 0;
    int m_statusUpdateCounter = 0;
};

#endif // TRAFFICSIGNDETECTSERVICE_H
