#ifndef PARKINGSPACEDETECTSERVICE_H
#define PARKINGSPACEDETECTSERVICE_H

#include <QAtomicInt>
#include <QImage>
#include <QObject>
#include <QUrl>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;
class StreamFrameImageProvider;

class ParkingSpaceDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultVideoUrl READ resultVideoUrl NOTIFY resultVideoUrlChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(int occupiedSpots READ occupiedSpots NOTIFY occupiedSpotsChanged)
    Q_PROPERTY(int totalSpots READ totalSpots NOTIFY totalSpotsChanged)
    Q_PROPERTY(int freeSpots READ freeSpots NOTIFY freeSpotsChanged)
    Q_PROPERTY(int vehicleCount READ vehicleCount NOTIFY vehicleCountChanged)
    Q_PROPERTY(double occupancyRate READ occupancyRate NOTIFY occupancyRateChanged)

public:
    explicit ParkingSpaceDetectService(QObject *parent = nullptr);
    ~ParkingSpaceDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultVideoUrl() const;
    QString statusMessage() const;
    int occupiedSpots() const;
    int totalSpots() const;
    int freeSpots() const;
    int vehicleCount() const;
    double occupancyRate() const;

    Q_INVOKABLE void detect(const QUrl &sourceVideoUrl,
                            const QUrl &parkingSpotsFileUrl = QUrl(),
                            bool realtimeDetect = true);
    Q_INVOKABLE bool openResultVideoWithSystemPlayer();
    Q_INVOKABLE void cancelDetect();

    static void setFrameImageProvider(StreamFrameImageProvider *provider);

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultVideoUrlChanged();
    void statusMessageChanged();
    void occupiedSpotsChanged();
    void totalSpotsChanged();
    void freeSpotsChanged();
    void vehicleCountChanged();
    void occupancyRateChanged();
    void frameDetected(int frameIndex, const QString &frameImageUrl);
    void detectFinished(bool success);

private:
    QString resolveBackendRoot() const;
    bool prepareUpload(const QUrl &sourceVideoUrl,
                       const QUrl &parkingSpotsFileUrl,
                       QString *destPath,
                       QString *parkingSpotsPath);
    void setBusy(bool value);
    void setErrorMessage(const QString &value);
    void setResultVideoUrl(const QString &value);
    void setStatusMessage(const QString &value);
    void setOccupiedSpots(int value);
    void setTotalSpots(int value);
    void setFreeSpots(int value);
    void setVehicleCount(int value);
    void setOccupancyRate(double value);
    void resetResultState();
    void cancelActiveRequest();
    void startDetect(const QString &destPath, const QString &parkingSpotsPath);
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
    int m_occupiedSpots = 0;
    int m_totalSpots = 0;
    int m_freeSpots = 0;
    int m_vehicleCount = 0;
    double m_occupancyRate = 0.0;
    int m_streamTotalFrames = 0;
    int m_statusUpdateCounter = 0;
};

#endif // PARKINGSPACEDETECTSERVICE_H
