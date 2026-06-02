#include "CarSpeedDetectService.h"
#include "StreamFrameImageProvider.h"

#include <QCoreApplication>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHttpMultiPart>
#include <QHttpPart>
#include <QJsonArray>
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
constexpr auto kDetectEndpoint = "/speedVideoDetected";
constexpr int kVideoRequestTimeoutMs = 600000;
constexpr int kStatusUpdateEveryNFrames = 10;

struct DecodedStreamFrame {
    int frameIndex = -1;
    QImage image;
    int vehicleCount = 0;
    bool detected = false;
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
    result.vehicleCount = data.value(QStringLiteral("vehicle_count")).toInt(0);
    result.detected = data.value(QStringLiteral("detected")).toBool(false);
    result.image = std::move(image);
    result.valid = true;
    return result;
}
} // namespace

StreamFrameImageProvider *CarSpeedDetectService::s_frameImageProvider = nullptr;

void CarSpeedDetectService::setFrameImageProvider(StreamFrameImageProvider *provider)
{
    s_frameImageProvider = provider;
}

CarSpeedDetectService::CarSpeedDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

CarSpeedDetectService::~CarSpeedDetectService()
{
    cancelActiveRequest();
}

bool CarSpeedDetectService::busy() const { return m_busy; }
QString CarSpeedDetectService::errorMessage() const { return m_errorMessage; }
QString CarSpeedDetectService::resultVideoUrl() const { return m_resultVideoUrl; }
QString CarSpeedDetectService::statusMessage() const { return m_statusMessage; }
double CarSpeedDetectService::maxSpeedKmh() const { return m_maxSpeedKmh; }
int CarSpeedDetectService::reliableVehicleCount() const { return m_reliableVehicleCount; }
QVariantList CarSpeedDetectService::speedList() const { return m_speedList; }

void CarSpeedDetectService::setBusy(bool v) { if (m_busy == v) return; m_busy = v; emit busyChanged(); }
void CarSpeedDetectService::setErrorMessage(const QString &v) { if (m_errorMessage == v) return; m_errorMessage = v; emit errorMessageChanged(); }
void CarSpeedDetectService::setResultVideoUrl(const QString &v) { if (m_resultVideoUrl == v) return; m_resultVideoUrl = v; emit resultVideoUrlChanged(); }
void CarSpeedDetectService::setStatusMessage(const QString &v) { if (m_statusMessage == v) return; m_statusMessage = v; emit statusMessageChanged(); }
void CarSpeedDetectService::setMaxSpeedKmh(double v) { if (qFuzzyCompare(m_maxSpeedKmh, v)) return; m_maxSpeedKmh = v; emit maxSpeedKmhChanged(); }
void CarSpeedDetectService::setReliableVehicleCount(int v) { if (m_reliableVehicleCount == v) return; m_reliableVehicleCount = v; emit reliableVehicleCountChanged(); }
void CarSpeedDetectService::setSpeedList(const QVariantList &v) { if (m_speedList == v) return; m_speedList = v; emit speedListChanged(); }

QString CarSpeedDetectService::resolveBackendRoot() const
{
    QDir dir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 6; ++i) {
        const QString candidate = dir.filePath(QStringLiteral("backend"));
        if (QFileInfo::exists(candidate + QStringLiteral("/main.py")))
            return QDir(candidate).absolutePath();
        if (!dir.cdUp()) break;
    }
    return QDir(QCoreApplication::applicationDirPath())
        .filePath(QStringLiteral("../../../backend"));
}

void CarSpeedDetectService::cancelActiveRequest()
{
    ++m_decodeJobId;
    m_lastDisplayedFrameIndex = -1;
    m_statusUpdateCounter = 0;
    if (!m_activeReply) return;
    m_activeReply->abort();
    m_activeReply->deleteLater();
    m_activeReply = nullptr;
    m_streamBuffer.clear();
}

void CarSpeedDetectService::detect(const QUrl &sourceVideoUrl,
                                   int frameInterval,
                                   double metersPerPixel,
                                   double referenceDistanceM,
                                   double referencePixels)
{
    if (m_busy) return;
    cancelActiveRequest();

    setErrorMessage({});
    setResultVideoUrl({});
    setStatusMessage({});
    setMaxSpeedKmh(0.0);
    setReliableVehicleCount(0);
    setSpeedList({});
    m_streamTotalFrames = 0;
    m_streamBuffer.clear();
    m_statusUpdateCounter = 0;
    m_lastDisplayedFrameIndex = -1;
    ++m_decodeJobId;

    const QString sourcePath = sourceVideoUrl.isLocalFile()
        ? sourceVideoUrl.toLocalFile()
        : sourceVideoUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的视频文件"));
        emit detectFinished(false);
        return;
    }

    const QString backendRoot = resolveBackendRoot();
    const QString uploadUuid = QUuid::createUuid().toString(QUuid::WithoutBraces);
    const QString uploadDirPath = QDir(backendRoot).filePath(
        QStringLiteral("upload/source/%1").arg(uploadUuid));

    QDir uploadDir;
    if (!uploadDir.mkpath(uploadDirPath)) {
        setErrorMessage(tr("无法创建上传目录：%1").arg(uploadDirPath));
        emit detectFinished(false);
        return;
    }

    const QFileInfo sourceInfo(sourcePath);
    const QString destPath = QDir(uploadDirPath).filePath(sourceInfo.fileName());
    if (QFile::exists(destPath)) QFile::remove(destPath);
    if (!QFile::copy(sourcePath, destPath)) {
        setErrorMessage(tr("复制视频到后端目录失败：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    setBusy(true);
    startDetect(destPath, frameInterval, metersPerPixel, referenceDistanceM, referencePixels);
}

bool CarSpeedDetectService::openResultVideoWithSystemPlayer()
{
    if (m_busy || m_resultVideoUrl.isEmpty()) return false;
    const QUrl resultUrl(m_resultVideoUrl);
    const QString localPath = resultUrl.isLocalFile()
        ? resultUrl.toLocalFile() : resultUrl.toString(QUrl::PreferLocalFile);
    if (localPath.isEmpty() || !QFileInfo::exists(localPath)) {
        setErrorMessage(tr("检测结果视频不存在：%1").arg(localPath.isEmpty() ? m_resultVideoUrl : localPath));
        return false;
    }
    return QDesktopServices::openUrl(QUrl::fromLocalFile(localPath));
}

void CarSpeedDetectService::cancelDetect()
{
    if (!m_busy) return;
    setBusy(false);
    cancelActiveRequest();
    setStatusMessage({});
    emit detectFinished(false);
}

void CarSpeedDetectService::startDetect(const QString &destPath, int interval,
                                         double mpp, double refDist, double refPx)
{
    setStatusMessage(tr("正在检测车速，请稍候..."));

    auto *multiPart = new QHttpMultiPart(QHttpMultiPart::FormDataType);

    auto *file = new QFile(destPath);
    if (!file->open(QIODevice::ReadOnly)) {
        delete file; delete multiPart;
        setBusy(false);
        setErrorMessage(tr("无法读取上传视频：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    QHttpPart filePart;
    filePart.setHeader(QNetworkRequest::ContentDispositionHeader,
                       QVariant(QStringLiteral("form-data; name=\"file\"; filename=\"%1\"")
                                    .arg(QFileInfo(destPath).fileName())));
    filePart.setHeader(QNetworkRequest::ContentTypeHeader,
                       QMimeDatabase().mimeTypeForFile(destPath).name());
    filePart.setBodyDevice(file);
    file->setParent(multiPart);
    multiPart->append(filePart);

    auto addTextPart = [&](const QString &name, const QByteArray &value) {
        QHttpPart part;
        part.setHeader(QNetworkRequest::ContentDispositionHeader,
                       QVariant(QStringLiteral("form-data; name=\"%1\"").arg(name)));
        part.setBody(value);
        multiPart->append(part);
    };

    addTextPart(QStringLiteral("frame_interval"), QByteArray::number(interval));
    addTextPart(QStringLiteral("meters_per_pixel"), QByteArray::number(mpp, 'f', 6));
    addTextPart(QStringLiteral("reference_distance_m"), QByteArray::number(refDist, 'f', 2));
    addTextPart(QStringLiteral("reference_pixels"), QByteArray::number(refPx, 'f', 2));

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kDetectEndpoint)));
    request.setTransferTimeout(kVideoRequestTimeoutMs);
    m_activeReply = m_networkManager->post(request, multiPart);
    multiPart->setParent(m_activeReply);

    connect(m_activeReply, &QNetworkReply::readyRead, this, [this]() {
        if (m_activeReply)
            appendStreamData(m_activeReply->readAll());
    });

    connect(m_activeReply, &QNetworkReply::finished, this, [this]() {
        if (!m_activeReply) return;
        appendStreamData(m_activeReply->readAll());
        if (m_busy && m_activeReply->error() != QNetworkReply::NoError)
            finishDetectFailed(tr("网络请求失败：%1").arg(m_activeReply->errorString()));
        else if (m_busy)
            finishDetectFailed(tr("测速连接意外结束"));
        m_activeReply->deleteLater();
        m_activeReply = nullptr;
    });
}

void CarSpeedDetectService::appendStreamData(const QByteArray &chunk)
{
    m_streamBuffer.append(chunk);
    int idx = -1;
    while ((idx = m_streamBuffer.indexOf('\n')) >= 0) {
        const QByteArray line = m_streamBuffer.left(idx).trimmed();
        m_streamBuffer.remove(0, idx + 1);
        if (!line.isEmpty())
            handleStreamLine(line);
    }
}

void CarSpeedDetectService::handleStreamLine(const QByteArray &line)
{
    if (line.startsWith("{\"event\":\"frame\"") || line.startsWith("{\"event\": \"frame\"")) {
        scheduleFrameDecode(line);
        return;
    }

    const QJsonDocument document = QJsonDocument::fromJson(line);
    if (!document.isObject()) return;

    const QJsonObject root = document.object();
    const QString event = root.value(QStringLiteral("event")).toString();
    const int code = root.value(QStringLiteral("code")).toInt(-1);
    const QString message = root.value(QStringLiteral("msg")).toString();
    const QJsonObject data = root.value(QStringLiteral("data")).toObject();

    if (event == QLatin1String("error") || code != 200) {
        finishDetectFailed(message.isEmpty() ? tr("车速检测失败") : message);
        return;
    }

    if (event == QLatin1String("start")) {
        m_streamTotalFrames = data.value(QStringLiteral("total_frames")).toInt(0);
        setStatusMessage(tr("车速检测中：共 %1 帧").arg(m_streamTotalFrames));
        return;
    }

    if (event == QLatin1String("done")) {
        const QString relativeUrl = data.value(QStringLiteral("url")).toString();
        const double maxSpeed = data.value(QStringLiteral("max_speed_kmh")).toDouble(0.0);
        const int reliableCount = data.value(QStringLiteral("reliable_vehicle_count")).toInt(0);
        const QJsonArray speedArray = data.value(QStringLiteral("speed_list")).toArray();

        const QString backendRoot = resolveBackendRoot();
        const QString absoluteResultPath = QDir(backendRoot).filePath(relativeUrl);
        if (!QFileInfo::exists(absoluteResultPath)) {
            finishDetectFailed(tr("检测结果视频不存在：%1").arg(absoluteResultPath));
            return;
        }

        QVariantList speeds;
        for (const auto &item : speedArray) {
            const QJsonObject obj = item.toObject();
            QVariantMap map;
            map[QStringLiteral("track_id")] = obj.value(QStringLiteral("track_id")).toInt();
            map[QStringLiteral("speed_kmh")] = obj.value(QStringLiteral("speed_kmh")).toDouble();
            map[QStringLiteral("class_name")] = obj.value(QStringLiteral("class_name")).toString();
            map[QStringLiteral("sample_count")] = obj.value(QStringLiteral("sample_count")).toInt();
            map[QStringLiteral("reliable")] = obj.value(QStringLiteral("reliable")).toBool();
            speeds.append(map);
        }

        setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
        setMaxSpeedKmh(maxSpeed);
        setReliableVehicleCount(reliableCount);
        setSpeedList(speeds);

        setStatusMessage(tr("检测完成：可靠车速 %1 辆，最高 %2 km/h")
                             .arg(reliableCount).arg(maxSpeed, 0, 'f', 1));
        setErrorMessage({});
        finishDetectSuccess();
        if (m_activeReply) m_activeReply->abort();
    }
}

void CarSpeedDetectService::scheduleFrameDecode(QByteArray line)
{
    const int jobId = m_decodeJobId.fetchAndAddAcquire(1) + 1;

    (void)QtConcurrent::run([this, line = std::move(line), jobId]() mutable {
        const DecodedStreamFrame decoded = decodeStreamFrameLine(line);
        if (!decoded.valid) return;

        QMetaObject::invokeMethod(this, [this, jobId, decoded]() {
            if (jobId != m_decodeJobId.loadAcquire()) return;
            if (decoded.frameIndex < m_lastDisplayedFrameIndex) return;

            m_lastDisplayedFrameIndex = decoded.frameIndex;
            publishFrame(decoded.frameIndex, decoded.image);

            ++m_statusUpdateCounter;
            if (m_statusUpdateCounter % kStatusUpdateEveryNFrames == 0) {
                if (m_streamTotalFrames > 0)
                    setStatusMessage(tr("车速检测中：第 %1 / %2 帧")
                                         .arg(decoded.frameIndex + 1).arg(m_streamTotalFrames));
                else
                    setStatusMessage(tr("车速检测中：第 %1 帧").arg(decoded.frameIndex + 1));
            }
        }, Qt::QueuedConnection);
    });
}

void CarSpeedDetectService::publishFrame(int frameIndex, const QImage &image)
{
    if (s_frameImageProvider)
        s_frameImageProvider->setFrame(frameIndex, image);

    const QString frameUrl = QStringLiteral("image://%1/%2")
                                 .arg(QLatin1String(StreamFrameImageProvider::kProviderId))
                                 .arg(frameIndex);
    emit frameDetected(frameIndex, frameUrl);
}

void CarSpeedDetectService::finishDetectFailed(const QString &message)
{
    if (!m_busy) return;
    cancelActiveRequest();
    setBusy(false);
    setErrorMessage(message);
    setStatusMessage({});
    emit detectFinished(false);
}

void CarSpeedDetectService::finishDetectSuccess()
{
    if (!m_busy) return;
    setBusy(false);
    emit detectFinished(true);
}
