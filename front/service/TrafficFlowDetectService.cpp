#include "TrafficFlowDetectService.h"
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
constexpr auto kDetectEndpoint = "/trafficVideoDetected";
constexpr int kVideoRequestTimeoutMs = 600000;
constexpr int kFrameInterval = 3;
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

QHttpMultiPart *createDetectMultipart(const QString &destPath, int lanes)
{
    auto *multiPart = new QHttpMultiPart(QHttpMultiPart::FormDataType);

    auto *file = new QFile(destPath);
    if (!file->open(QIODevice::ReadOnly)) {
        delete file;
        delete multiPart;
        return nullptr;
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

    appendTextPart(multiPart, QStringLiteral("num_lanes"), QByteArray::number(qMax(1, lanes)));
    appendTextPart(multiPart, QStringLiteral("frame_interval"), QByteArray::number(kFrameInterval));
    return multiPart;
}
} // namespace

StreamFrameImageProvider *TrafficFlowDetectService::s_frameImageProvider = nullptr;

void TrafficFlowDetectService::setFrameImageProvider(StreamFrameImageProvider *provider)
{
    s_frameImageProvider = provider;
}

TrafficFlowDetectService::TrafficFlowDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

TrafficFlowDetectService::~TrafficFlowDetectService()
{
    cancelActiveRequest();
}

bool TrafficFlowDetectService::busy() const { return m_busy; }
QString TrafficFlowDetectService::errorMessage() const { return m_errorMessage; }
QString TrafficFlowDetectService::resultVideoUrl() const { return m_resultVideoUrl; }
QString TrafficFlowDetectService::statusMessage() const { return m_statusMessage; }
int TrafficFlowDetectService::uniqueVehicleCount() const { return m_uniqueVehicleCount; }
double TrafficFlowDetectService::hourlyTrafficRatio() const { return m_hourlyTrafficRatio; }
QString TrafficFlowDetectService::roadCondition() const { return m_roadCondition; }
int TrafficFlowDetectService::numLanes() const { return m_numLanes; }
double TrafficFlowDetectService::durationSec() const { return m_durationSec; }

void TrafficFlowDetectService::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void TrafficFlowDetectService::setErrorMessage(const QString &value)
{
    if (m_errorMessage == value)
        return;
    m_errorMessage = value;
    emit errorMessageChanged();
}

void TrafficFlowDetectService::setResultVideoUrl(const QString &value)
{
    if (m_resultVideoUrl == value)
        return;
    m_resultVideoUrl = value;
    emit resultVideoUrlChanged();
}

void TrafficFlowDetectService::setStatusMessage(const QString &value)
{
    if (m_statusMessage == value)
        return;
    m_statusMessage = value;
    emit statusMessageChanged();
}

void TrafficFlowDetectService::setUniqueVehicleCount(int value)
{
    if (m_uniqueVehicleCount == value)
        return;
    m_uniqueVehicleCount = value;
    emit uniqueVehicleCountChanged();
}

void TrafficFlowDetectService::setHourlyTrafficRatio(double value)
{
    if (qFuzzyCompare(m_hourlyTrafficRatio + 1.0, value + 1.0))
        return;
    m_hourlyTrafficRatio = value;
    emit hourlyTrafficRatioChanged();
}

void TrafficFlowDetectService::setRoadCondition(const QString &value)
{
    if (m_roadCondition == value)
        return;
    m_roadCondition = value;
    emit roadConditionChanged();
}

void TrafficFlowDetectService::setNumLanes(int value)
{
    value = qMax(1, value);
    if (m_numLanes == value)
        return;
    m_numLanes = value;
    emit numLanesChanged();
}

void TrafficFlowDetectService::setDurationSec(double value)
{
    if (qFuzzyCompare(m_durationSec + 1.0, value + 1.0))
        return;
    m_durationSec = value;
    emit durationSecChanged();
}

QString TrafficFlowDetectService::resolveBackendRoot() const
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

void TrafficFlowDetectService::resetResultState()
{
    setErrorMessage({});
    setResultVideoUrl({});
    setStatusMessage({});
    setUniqueVehicleCount(0);
    setHourlyTrafficRatio(0.0);
    setRoadCondition({});
    setDurationSec(0.0);
    m_streamTotalFrames = 0;
    m_statusUpdateCounter = 0;
    m_lastDisplayedFrameIndex = -1;
    m_streamBuffer.clear();
}

void TrafficFlowDetectService::cancelActiveRequest()
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

bool TrafficFlowDetectService::prepareUpload(const QUrl &sourceVideoUrl, QString *destPath)
{
    const QString sourcePath = sourceVideoUrl.isLocalFile()
                                   ? sourceVideoUrl.toLocalFile()
                                   : sourceVideoUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的视频文件"));
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
    return true;
}

void TrafficFlowDetectService::detect(const QUrl &sourceVideoUrl, int lanes, bool realtimeDetect)
{
    Q_UNUSED(realtimeDetect)

    if (m_busy)
        return;

    cancelActiveRequest();
    resetResultState();
    setNumLanes(lanes);
    ++m_decodeJobId;

    QString destPath;
    if (!prepareUpload(sourceVideoUrl, &destPath)) {
        emit detectFinished(false);
        return;
    }

    setBusy(true);
    startDetect(destPath, lanes);
}

bool TrafficFlowDetectService::openResultVideoWithSystemPlayer()
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

void TrafficFlowDetectService::cancelDetect()
{
    if (!m_busy)
        return;

    setBusy(false);
    cancelActiveRequest();
    setStatusMessage({});
    emit detectFinished(false);
}

void TrafficFlowDetectService::startDetect(const QString &destPath, int lanes)
{
    setStatusMessage(tr("正在检测，请稍候..."));

    auto *multiPart = createDetectMultipart(destPath, lanes);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传视频：%1").arg(destPath));
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

void TrafficFlowDetectService::appendStreamData(const QByteArray &chunk)
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

void TrafficFlowDetectService::handleStreamLine(const QByteArray &line)
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
        finishDetectFailed(message.isEmpty() ? tr("车流量检测失败") : message);
        return;
    }

    if (event == QLatin1String("start")) {
        m_streamTotalFrames = data.value(QStringLiteral("total_frames")).toInt(0);
        setNumLanes(data.value(QStringLiteral("num_lanes")).toInt(m_numLanes));
        setDurationSec(data.value(QStringLiteral("duration_sec")).toDouble(0.0));
        setStatusMessage(tr("车流量检测中：共 %1 帧").arg(m_streamTotalFrames));
        return;
    }

    if (event == QLatin1String("frame")) {
        setUniqueVehicleCount(data.value(QStringLiteral("unique_vehicle_count")).toInt(m_uniqueVehicleCount));
        scheduleFrameDecode(line);
        return;
    }

    if (event == QLatin1String("done")) {
        const QString relativeUrl = data.value(QStringLiteral("url")).toString();
        const QString absoluteResultPath = QDir(resolveBackendRoot()).filePath(relativeUrl);
        if (!QFileInfo::exists(absoluteResultPath)) {
            finishDetectFailed(tr("检测结果视频不存在：%1").arg(absoluteResultPath));
            return;
        }

        const int vehicles = data.value(QStringLiteral("unique_vehicle_count")).toInt(0);
        const double hourlyRatio = data.value(QStringLiteral("hourly_traffic_ratio")).toDouble(0.0);
        const QString condition = data.value(QStringLiteral("road_condition")).toString();
        const int lanes = data.value(QStringLiteral("num_lanes")).toInt(m_numLanes);
        const double duration = data.value(QStringLiteral("duration_sec")).toDouble(0.0);

        setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
        setUniqueVehicleCount(vehicles);
        setHourlyTrafficRatio(hourlyRatio);
        setRoadCondition(condition);
        setNumLanes(lanes);
        setDurationSec(duration);
        setStatusMessage(tr("检测完成：唯一车辆 %1，小时流量 %2 辆/h，道路%3")
                             .arg(vehicles)
                             .arg(hourlyRatio, 0, 'f', 0)
                             .arg(condition));
        setErrorMessage({});
        finishDetectSuccess();
        if (m_activeReply)
            m_activeReply->abort();
    }
}

void TrafficFlowDetectService::scheduleFrameDecode(QByteArray line)
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
                    setStatusMessage(tr("车流量检测中：第 %1 / %2 帧")
                                         .arg(decoded.frameIndex + 1)
                                         .arg(m_streamTotalFrames));
                } else {
                    setStatusMessage(tr("车流量检测中：第 %1 帧").arg(decoded.frameIndex + 1));
                }
            }
        }, Qt::QueuedConnection);
    });
}

void TrafficFlowDetectService::publishFrame(int frameIndex, const QImage &image)
{
    if (s_frameImageProvider)
        s_frameImageProvider->setFrame(frameIndex, image);

    const QString frameUrl = QStringLiteral("image://%1/%2")
                                 .arg(QLatin1String(StreamFrameImageProvider::kProviderId))
                                 .arg(frameIndex);
    emit frameDetected(frameIndex, frameUrl);
}

void TrafficFlowDetectService::finishDetectFailed(const QString &message)
{
    if (!m_busy)
        return;

    cancelActiveRequest();
    setBusy(false);
    setErrorMessage(message);
    setStatusMessage({});
    emit detectFinished(false);
}

void TrafficFlowDetectService::finishDetectSuccess()
{
    if (!m_busy)
        return;

    setBusy(false);
    emit detectFinished(true);
}
