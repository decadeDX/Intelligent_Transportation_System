#include "ParkingSpaceDetectService.h"
#include "StreamFrameImageProvider.h"

#include <QCoreApplication>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHttpMultiPart>
#include <QHttpPart>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaObject>
#include <QMimeDatabase>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUuid>
#include <QtConcurrent/QtConcurrent>

namespace {
constexpr auto kApiBaseUrl = "http://127.0.0.1:8000";
constexpr auto kDetectEndpoint = "/parkVideoDetectedWithFrame";
constexpr int kVideoRequestTimeoutMs = 600000;
constexpr int kFrameInterval = 5;
constexpr int kStatusUpdateEveryNFrames = 10;

struct DecodedStreamFrame {
    int frameIndex = -1;
    QImage image;
    bool valid = false;
};

DecodedStreamFrame decodeStreamFrameLine(const QByteArray &line)
{
    DecodedStreamFrame result;

    const QJsonDocument document = QJsonDocument::fromJson(line);
    if (!document.isObject())
        return result;

    const QJsonObject root = document.object();
    if (root.value(QStringLiteral("event")).toString() != QLatin1String("frame"))
        return result;

    const QJsonObject data = root.value(QStringLiteral("data")).toObject();
    const QByteArray encoded = data.value(QStringLiteral("frame_jpeg_base64")).toString().toLatin1();
    if (encoded.isEmpty())
        return result;

    QImage image;
    if (!image.loadFromData(QByteArray::fromBase64(encoded), "JPEG"))
        return result;

    result.frameIndex = data.value(QStringLiteral("frame_index")).toInt(0);
    result.image = std::move(image);
    result.valid = true;
    return result;
}

void appendTextPart(QHttpMultiPart *multiPart, const QString &name, const QByteArray &value)
{
    QHttpPart part;
    part.setHeader(QNetworkRequest::ContentDispositionHeader,
                   QVariant(QStringLiteral("form-data; name=\"%1\"").arg(name)));
    part.setBody(value);
    multiPart->append(part);
}

bool appendFilePart(QHttpMultiPart *multiPart, const QString &fieldName, const QString &path)
{
    auto *file = new QFile(path);
    if (!file->open(QIODevice::ReadOnly)) {
        delete file;
        return false;
    }

    QHttpPart filePart;
    filePart.setHeader(QNetworkRequest::ContentDispositionHeader,
                       QVariant(QStringLiteral("form-data; name=\"%1\"; filename=\"%2\"")
                                    .arg(fieldName, QFileInfo(path).fileName())));
    filePart.setHeader(QNetworkRequest::ContentTypeHeader,
                       QMimeDatabase().mimeTypeForFile(path).name());
    filePart.setBodyDevice(file);
    file->setParent(multiPart);
    multiPart->append(filePart);
    return true;
}

QHttpMultiPart *createDetectMultipart(const QString &destPath, const QString &parkingSpotsPath)
{
    auto *multiPart = new QHttpMultiPart(QHttpMultiPart::FormDataType);

    if (!appendFilePart(multiPart, QStringLiteral("file"), destPath)) {
        delete multiPart;
        return nullptr;
    }

    if (!parkingSpotsPath.isEmpty()
        && !appendFilePart(multiPart, QStringLiteral("parking_spots_file"), parkingSpotsPath)) {
        delete multiPart;
        return nullptr;
    }

    appendTextPart(multiPart, QStringLiteral("frame_interval"), QByteArray::number(kFrameInterval));
    return multiPart;
}
} // namespace

StreamFrameImageProvider *ParkingSpaceDetectService::s_frameImageProvider = nullptr;

void ParkingSpaceDetectService::setFrameImageProvider(StreamFrameImageProvider *provider)
{
    s_frameImageProvider = provider;
}

ParkingSpaceDetectService::ParkingSpaceDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

ParkingSpaceDetectService::~ParkingSpaceDetectService()
{
    cancelActiveRequest();
}

bool ParkingSpaceDetectService::busy() const { return m_busy; }
QString ParkingSpaceDetectService::errorMessage() const { return m_errorMessage; }
QString ParkingSpaceDetectService::resultVideoUrl() const { return m_resultVideoUrl; }
QString ParkingSpaceDetectService::statusMessage() const { return m_statusMessage; }
int ParkingSpaceDetectService::occupiedSpots() const { return m_occupiedSpots; }
int ParkingSpaceDetectService::totalSpots() const { return m_totalSpots; }
int ParkingSpaceDetectService::freeSpots() const { return m_freeSpots; }
int ParkingSpaceDetectService::vehicleCount() const { return m_vehicleCount; }
double ParkingSpaceDetectService::occupancyRate() const { return m_occupancyRate; }

void ParkingSpaceDetectService::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void ParkingSpaceDetectService::setErrorMessage(const QString &value)
{
    if (m_errorMessage == value)
        return;
    m_errorMessage = value;
    emit errorMessageChanged();
}

void ParkingSpaceDetectService::setResultVideoUrl(const QString &value)
{
    if (m_resultVideoUrl == value)
        return;
    m_resultVideoUrl = value;
    emit resultVideoUrlChanged();
}

void ParkingSpaceDetectService::setStatusMessage(const QString &value)
{
    if (m_statusMessage == value)
        return;
    m_statusMessage = value;
    emit statusMessageChanged();
}

void ParkingSpaceDetectService::setOccupiedSpots(int value)
{
    if (m_occupiedSpots == value)
        return;
    m_occupiedSpots = value;
    emit occupiedSpotsChanged();
}

void ParkingSpaceDetectService::setTotalSpots(int value)
{
    if (m_totalSpots == value)
        return;
    m_totalSpots = value;
    emit totalSpotsChanged();
}

void ParkingSpaceDetectService::setFreeSpots(int value)
{
    if (m_freeSpots == value)
        return;
    m_freeSpots = value;
    emit freeSpotsChanged();
}

void ParkingSpaceDetectService::setVehicleCount(int value)
{
    if (m_vehicleCount == value)
        return;
    m_vehicleCount = value;
    emit vehicleCountChanged();
}

void ParkingSpaceDetectService::setOccupancyRate(double value)
{
    if (qFuzzyCompare(m_occupancyRate + 1.0, value + 1.0))
        return;
    m_occupancyRate = value;
    emit occupancyRateChanged();
}

QString ParkingSpaceDetectService::resolveBackendRoot() const
{
    QDir dir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 6; ++i) {
        const QString candidate = dir.filePath(QStringLiteral("backend"));
        if (QFileInfo::exists(candidate + QStringLiteral("/main.py")))
            return QDir(candidate).absolutePath();
        if (!dir.cdUp())
            break;
    }

    return QDir(QCoreApplication::applicationDirPath())
        .filePath(QStringLiteral("../../../backend"));
}

void ParkingSpaceDetectService::resetResultState()
{
    setErrorMessage({});
    setResultVideoUrl({});
    setStatusMessage({});
    setOccupiedSpots(0);
    setTotalSpots(0);
    setFreeSpots(0);
    setVehicleCount(0);
    setOccupancyRate(0.0);
    m_streamTotalFrames = 0;
    m_statusUpdateCounter = 0;
    m_lastDisplayedFrameIndex = -1;
    m_streamBuffer.clear();
}

void ParkingSpaceDetectService::cancelActiveRequest()
{
    ++m_decodeJobId;
    m_lastDisplayedFrameIndex = -1;
    m_statusUpdateCounter = 0;

    if (!m_activeReply)
        return;

    m_activeReply->abort();
    m_activeReply->deleteLater();
    m_activeReply = nullptr;
    m_streamBuffer.clear();
}

bool ParkingSpaceDetectService::prepareUpload(const QUrl &sourceVideoUrl,
                                              const QUrl &parkingSpotsFileUrl,
                                              QString *destPath,
                                              QString *parkingSpotsPath)
{
    const QString sourcePath = sourceVideoUrl.isLocalFile()
                                   ? sourceVideoUrl.toLocalFile()
                                   : sourceVideoUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的视频文件"));
        return false;
    }

    const QString spotsSourcePath = parkingSpotsFileUrl.isEmpty()
                                        ? QString()
                                        : (parkingSpotsFileUrl.isLocalFile()
                                               ? parkingSpotsFileUrl.toLocalFile()
                                               : parkingSpotsFileUrl.toString(QUrl::PreferLocalFile));
    if (!spotsSourcePath.isEmpty() && !QFileInfo::exists(spotsSourcePath)) {
        setErrorMessage(tr("车位信息文件不存在：%1").arg(spotsSourcePath));
        return false;
    }

    const QString backendRoot = resolveBackendRoot();
    const QString uploadUuid = QUuid::createUuid().toString(QUuid::WithoutBraces);
    const QString uploadDirPath = QDir(backendRoot).filePath(
        QStringLiteral("upload/source/%1").arg(uploadUuid));

    QDir uploadDir;
    if (!uploadDir.mkpath(uploadDirPath)) {
        setErrorMessage(tr("无法创建上传目录：%1").arg(uploadDirPath));
        return false;
    }

    const QFileInfo sourceInfo(sourcePath);
    const QString targetPath = QDir(uploadDirPath).filePath(sourceInfo.fileName());

    if (QFile::exists(targetPath))
        QFile::remove(targetPath);
    if (!QFile::copy(sourcePath, targetPath)) {
        setErrorMessage(tr("复制视频到后端目录失败：%1").arg(targetPath));
        return false;
    }

    *destPath = targetPath;
    parkingSpotsPath->clear();

    if (!spotsSourcePath.isEmpty()) {
        const QFileInfo spotsInfo(spotsSourcePath);
        const QString targetSpotsPath = QDir(uploadDirPath).filePath(spotsInfo.fileName());

        if (QFile::exists(targetSpotsPath))
            QFile::remove(targetSpotsPath);
        if (!QFile::copy(spotsSourcePath, targetSpotsPath)) {
            setErrorMessage(tr("复制车位信息文件到后端目录失败：%1").arg(targetSpotsPath));
            return false;
        }

        *parkingSpotsPath = targetSpotsPath;
    }

    return true;
}

void ParkingSpaceDetectService::detect(const QUrl &sourceVideoUrl,
                                       const QUrl &parkingSpotsFileUrl,
                                       bool realtimeDetect)
{
    Q_UNUSED(realtimeDetect)

    if (m_busy)
        return;

    cancelActiveRequest();
    resetResultState();
    ++m_decodeJobId;

    QString destPath;
    QString parkingSpotsPath;
    if (!prepareUpload(sourceVideoUrl, parkingSpotsFileUrl, &destPath, &parkingSpotsPath)) {
        emit detectFinished(false);
        return;
    }

    setBusy(true);
    startDetect(destPath, parkingSpotsPath);
}

bool ParkingSpaceDetectService::openResultVideoWithSystemPlayer()
{
    if (m_busy || m_resultVideoUrl.isEmpty())
        return false;

    const QUrl resultUrl(m_resultVideoUrl);
    const QString localPath = resultUrl.isLocalFile()
                                  ? resultUrl.toLocalFile()
                                  : resultUrl.toString(QUrl::PreferLocalFile);

    if (localPath.isEmpty() || !QFileInfo::exists(localPath)) {
        setErrorMessage(tr("检测结果视频不存在：%1").arg(localPath.isEmpty() ? m_resultVideoUrl : localPath));
        return false;
    }

    const bool opened = QDesktopServices::openUrl(QUrl::fromLocalFile(localPath));
    if (!opened)
        setErrorMessage(tr("无法使用系统默认播放器打开视频"));
    return opened;
}

void ParkingSpaceDetectService::cancelDetect()
{
    if (!m_busy)
        return;

    setBusy(false);
    cancelActiveRequest();
    setStatusMessage({});
    emit detectFinished(false);
}

void ParkingSpaceDetectService::startDetect(const QString &destPath, const QString &parkingSpotsPath)
{
    setStatusMessage(tr("正在检测，请稍候..."));

    auto *multiPart = createDetectMultipart(destPath, parkingSpotsPath);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(parkingSpotsPath.isEmpty()
                            ? tr("无法读取上传视频：%1").arg(destPath)
                            : tr("无法读取上传视频或车位信息文件"));
        emit detectFinished(false);
        return;
    }

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kDetectEndpoint)));
    request.setTransferTimeout(kVideoRequestTimeoutMs);
    m_activeReply = m_networkManager->post(request, multiPart);
    multiPart->setParent(m_activeReply);

    connect(m_activeReply, &QNetworkReply::readyRead, this, [this]() {
        if (m_activeReply)
            appendStreamData(m_activeReply->readAll());
    });

    connect(m_activeReply, &QNetworkReply::finished, this, [this]() {
        if (!m_activeReply)
            return;

        appendStreamData(m_activeReply->readAll());
        if (m_busy && m_activeReply->error() != QNetworkReply::NoError)
            finishDetectFailed(tr("网络请求失败：%1").arg(m_activeReply->errorString()));
        else if (m_busy)
            finishDetectFailed(tr("检测连接意外结束"));

        m_activeReply->deleteLater();
        m_activeReply = nullptr;
    });
}

void ParkingSpaceDetectService::appendStreamData(const QByteArray &chunk)
{
    m_streamBuffer.append(chunk);

    int newlineIndex = -1;
    while ((newlineIndex = m_streamBuffer.indexOf('\n')) >= 0) {
        const QByteArray line = m_streamBuffer.left(newlineIndex).trimmed();
        m_streamBuffer.remove(0, newlineIndex + 1);
        if (!line.isEmpty())
            handleStreamLine(line);
    }
}

void ParkingSpaceDetectService::handleStreamLine(const QByteArray &line)
{
    const QJsonDocument document = QJsonDocument::fromJson(line);
    if (!document.isObject())
        return;

    const QJsonObject root = document.object();
    const QString event = root.value(QStringLiteral("event")).toString();
    const int code = root.value(QStringLiteral("code")).toInt(-1);
    const QString message = root.value(QStringLiteral("msg")).toString();
    const QJsonObject data = root.value(QStringLiteral("data")).toObject();

    if (event == QLatin1String("error") || code != 200) {
        finishDetectFailed(message.isEmpty() ? tr("车位检测失败") : message);
        return;
    }

    if (event == QLatin1String("start")) {
        m_streamTotalFrames = data.value(QStringLiteral("total_frames")).toInt(0);
        setStatusMessage(tr("车位检测中：共 %1 帧").arg(m_streamTotalFrames));
        return;
    }

    if (event == QLatin1String("frame")) {
        const int total = data.value(QStringLiteral("total_spots")).toInt(m_totalSpots);
        const int occupied = data.value(QStringLiteral("occupied_spots")).toInt(m_occupiedSpots);
        const int free = data.value(QStringLiteral("free_spots")).toInt(qMax(0, total - occupied));
        setTotalSpots(total);
        setOccupiedSpots(occupied);
        setFreeSpots(free);
        setVehicleCount(data.value(QStringLiteral("vehicle_count")).toInt(m_vehicleCount));
        setOccupancyRate(total > 0 ? double(occupied) / double(total) : 0.0);
        scheduleFrameDecode(line);
        return;
    }

    if (event == QLatin1String("done")) {
        const QString relativeUrl = data.value(QStringLiteral("url")).toString();
        const int total = data.value(QStringLiteral("total_spots")).toInt(0);
        const int occupied = data.value(QStringLiteral("occupied_spots")).toInt(0);
        const int free = data.value(QStringLiteral("free_spots")).toInt(qMax(0, total - occupied));
        const double rate = data.value(QStringLiteral("occupancy_rate")).toDouble(
            total > 0 ? double(occupied) / double(total) : 0.0);

        const QString absoluteResultPath = QDir(resolveBackendRoot()).filePath(relativeUrl);
        if (!QFileInfo::exists(absoluteResultPath)) {
            finishDetectFailed(tr("检测结果视频不存在：%1").arg(absoluteResultPath));
            return;
        }

        setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
        setTotalSpots(total);
        setOccupiedSpots(occupied);
        setFreeSpots(free);
        setOccupancyRate(rate);
        setStatusMessage(tr("检测完成：总车位 %1，已占用 %2，空闲 %3，占用率 %4%")
                             .arg(total)
                             .arg(occupied)
                             .arg(free)
                             .arg(rate * 100.0, 0, 'f', 1));
        setErrorMessage({});
        finishDetectSuccess();
        if (m_activeReply)
            m_activeReply->abort();
    }
}

void ParkingSpaceDetectService::scheduleFrameDecode(QByteArray line)
{
    const int jobId = m_decodeJobId.fetchAndAddAcquire(1) + 1;

    (void)QtConcurrent::run([this, line = std::move(line), jobId]() mutable {
        const DecodedStreamFrame decoded = decodeStreamFrameLine(line);
        if (!decoded.valid)
            return;

        QMetaObject::invokeMethod(this, [this, jobId, decoded]() {
            if (jobId != m_decodeJobId.loadAcquire())
                return;
            if (decoded.frameIndex < m_lastDisplayedFrameIndex)
                return;

            m_lastDisplayedFrameIndex = decoded.frameIndex;
            publishFrame(decoded.frameIndex, decoded.image);

            ++m_statusUpdateCounter;
            if (m_statusUpdateCounter % kStatusUpdateEveryNFrames == 0) {
                if (m_streamTotalFrames > 0) {
                    setStatusMessage(tr("车位检测中：第 %1 / %2 帧")
                                         .arg(decoded.frameIndex + 1)
                                         .arg(m_streamTotalFrames));
                } else {
                    setStatusMessage(tr("车位检测中：第 %1 帧").arg(decoded.frameIndex + 1));
                }
            }
        }, Qt::QueuedConnection);
    });
}

void ParkingSpaceDetectService::publishFrame(int frameIndex, const QImage &image)
{
    if (s_frameImageProvider)
        s_frameImageProvider->setFrame(frameIndex, image);

    const QString frameUrl = QStringLiteral("image://%1/%2")
                                 .arg(QLatin1String(StreamFrameImageProvider::kProviderId))
                                 .arg(frameIndex);
    emit frameDetected(frameIndex, frameUrl);
}

void ParkingSpaceDetectService::finishDetectFailed(const QString &message)
{
    if (!m_busy)
        return;

    cancelActiveRequest();
    setBusy(false);
    setErrorMessage(message);
    setStatusMessage({});
    emit detectFinished(false);
}

void ParkingSpaceDetectService::finishDetectSuccess()
{
    if (!m_busy)
        return;

    setBusy(false);
    emit detectFinished(true);
}
