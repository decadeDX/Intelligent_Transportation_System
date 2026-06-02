#ifndef CARSPEEDDETECTSERVICE_H
#define CARSPEEDDETECTSERVICE_H

#include <QAtomicInt>
#include <QImage>
#include <QObject>
#include <QUrl>
#include <QVariantList>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;
class StreamFrameImageProvider;

/// 视频车速检测服务：封装 /speedVideoDetected（NDJSON 逐帧流式）
class CarSpeedDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultVideoUrl READ resultVideoUrl NOTIFY resultVideoUrlChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(double maxSpeedKmh READ maxSpeedKmh NOTIFY maxSpeedKmhChanged)
    Q_PROPERTY(int reliableVehicleCount READ reliableVehicleCount NOTIFY reliableVehicleCountChanged)
    Q_PROPERTY(QVariantList speedList READ speedList NOTIFY speedListChanged)

public:
    explicit CarSpeedDetectService(QObject *parent = nullptr);
    ~CarSpeedDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultVideoUrl() const;
    QString statusMessage() const;
    double maxSpeedKmh() const;
    int reliableVehicleCount() const;
    QVariantList speedList() const;

    /// 发起视频车速检测
    Q_INVOKABLE void detect(const QUrl &sourceVideoUrl,
                            int frameInterval = 1,
                            double metersPerPixel = 0.1,
                            double referenceDistanceM = 0.0,
                            double referencePixels = 0.0);
    Q_INVOKABLE bool openResultVideoWithSystemPlayer();
    Q_INVOKABLE void cancelDetect();

    static void setFrameImageProvider(StreamFrameImageProvider *provider);

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultVideoUrlChanged();
    void statusMessageChanged();
    void maxSpeedKmhChanged();
    void reliableVehicleCountChanged();
    void speedListChanged();
    void frameDetected(int frameIndex, const QString &frameImageUrl);
    void detectFinished(bool success);

private:
    QString resolveBackendRoot() const;
    void setBusy(bool v);
    void setErrorMessage(const QString &v);
    void setResultVideoUrl(const QString &v);
    void setStatusMessage(const QString &v);
    void setMaxSpeedKmh(double v);
    void setReliableVehicleCount(int v);
    void setSpeedList(const QVariantList &v);
    void cancelActiveRequest();
    void startDetect(const QString &destPath, int interval,
                     double mpp, double refDist, double refPx);
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
    double m_maxSpeedKmh = 0.0;
    int m_reliableVehicleCount = 0;
    QVariantList m_speedList;
    int m_streamTotalFrames = 0;
    int m_statusUpdateCounter = 0;
};

#endif // CARSPEEDDETECTSERVICE_H
