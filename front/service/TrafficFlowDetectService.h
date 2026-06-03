#ifndef TRAFFICFLOWDETECTSERVICE_H
#define TRAFFICFLOWDETECTSERVICE_H

#include <QAtomicInt>
#include <QImage>
#include <QObject>
#include <QUrl>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;
class StreamFrameImageProvider;

class TrafficFlowDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultVideoUrl READ resultVideoUrl NOTIFY resultVideoUrlChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(int uniqueVehicleCount READ uniqueVehicleCount NOTIFY uniqueVehicleCountChanged)
    Q_PROPERTY(double hourlyTrafficRatio READ hourlyTrafficRatio NOTIFY hourlyTrafficRatioChanged)
    Q_PROPERTY(QString roadCondition READ roadCondition NOTIFY roadConditionChanged)
    Q_PROPERTY(int numLanes READ numLanes NOTIFY numLanesChanged)
    Q_PROPERTY(double durationSec READ durationSec NOTIFY durationSecChanged)

public:
    explicit TrafficFlowDetectService(QObject *parent = nullptr);
    ~TrafficFlowDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultVideoUrl() const;
    QString statusMessage() const;
    int uniqueVehicleCount() const;
    double hourlyTrafficRatio() const;
    QString roadCondition() const;
    int numLanes() const;
    double durationSec() const;

    Q_INVOKABLE void detect(const QUrl &sourceVideoUrl,
                            int numLanes = 1,
                            bool realtimeDetect = true);
    Q_INVOKABLE bool openResultVideoWithSystemPlayer();
    Q_INVOKABLE void cancelDetect();

    static void setFrameImageProvider(StreamFrameImageProvider *provider);

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultVideoUrlChanged();
    void statusMessageChanged();
    void uniqueVehicleCountChanged();
    void hourlyTrafficRatioChanged();
    void roadConditionChanged();
    void numLanesChanged();
    void durationSecChanged();
    void frameDetected(int frameIndex, const QString &frameImageUrl);
    void detectFinished(bool success);

private:
    QString resolveBackendRoot() const;
    bool prepareUpload(const QUrl &sourceVideoUrl, QString *destPath);
    void setBusy(bool value);
    void setErrorMessage(const QString &value);
    void setResultVideoUrl(const QString &value);
    void setStatusMessage(const QString &value);
    void setUniqueVehicleCount(int value);
    void setHourlyTrafficRatio(double value);
    void setRoadCondition(const QString &value);
    void setNumLanes(int value);
    void setDurationSec(double value);
    void resetResultState();
    void cancelActiveRequest();
    void startDetect(const QString &destPath, int lanes);
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
    int m_uniqueVehicleCount = 0;
    double m_hourlyTrafficRatio = 0.0;
    QString m_roadCondition;
    int m_numLanes = 1;
    double m_durationSec = 0.0;
    int m_streamTotalFrames = 0;
    int m_statusUpdateCounter = 0;
};

#endif // TRAFFICFLOWDETECTSERVICE_H
