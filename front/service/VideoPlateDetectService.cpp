#include "VideoPlateDetectService.h"
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
constexpr auto kBatchEndpoint = "/plateVideoDetected";
constexpr auto kStreamEndpoint = "/plateVideoDetectedWithFrame";
constexpr int kVideoRequestTimeoutMs = 600000;
constexpr int kFrameInterval = 5;
constexpr int kStatusUpdateEveryNFrames = 10;

struct DecodedStreamFrame {
    int frameIndex = -1;
    QImage image;
    int plateNumber = 0;
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
    result.plateNumber = data.value(QStringLiteral("plate_number")).toInt(0);
    result.detected = data.value(QStringLiteral("detected")).toBool(false);
    result.image = std::move(image);
    result.valid = true;
    return result;
}
} // namespace

StreamFrameImageProvider *VideoPlateDetectService::s_frameImageProvider = nullptr;

void VideoPlateDetectService::setFrameImageProvider(StreamFrameImageProvider *provider)
{
    s_frameImageProvider = provider;
}

VideoPlateDetectService::VideoPlateDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

VideoPlateDetectService::~VideoPlateDetectService()
{
    cancelActiveRequest();
}

bool VideoPlateDetectService::busy() const { return m_busy; }
bool VideoPlateDetectService::realtimeDetect() const { return m_realtimeDetect; }
QString VideoPlateDetectService::errorMessage() const { return m_errorMessage; }
QString VideoPlateDetectService::resultVideoUrl() const { return m_resultVideoUrl; }
int VideoPlateDetectService::detectionCount() const { return m_detectionCount; }
QString VideoPlateDetectService::statusMessage() const { return m_statusMessage; }
QVariantList VideoPlateDetectService::plateList() const { return m_plateList; }

void VideoPlateDetectService::setBusy(bool v)
{
    if (m_busy == v) return;
    m_busy = v;
    emit busyChanged();
}

void VideoPlateDetectService::setRealtimeDetect(bool v)
{
    if (m_realtimeDetect == v) return;
    m_realtimeDetect = v;
    emit realtimeDetectChanged();
}

void VideoPlateDetectService::setErrorMessage(const QString &v)
{
    if (m_errorMessage == v) return;
    m_errorMessage = v;
    emit errorMessageChanged();
}

void VideoPlateDetectService::setResultVideoUrl(const QString &v)
{
    if (m_resultVideoUrl == v) return;
    m_resultVideoUrl = v;
    emit resultVideoUrlChanged();
}

void VideoPlateDetectService::setDetectionCount(int v)
{
    if (m_detectionCount == v) return;
    m_detectionCount = v;
    emit detectionCountChanged();
}

void VideoPlateDetectService::setStatusMessage(const QString &v)
{
    if (m_statusMessage == v) return;
    m_statusMessage = v;
    emit statusMessageChanged();
}

void VideoPlateDetectService::setPlateList(const QVariantList &v)
{
    if (m_plateList == v) return;
    m_plateList = v;
    emit plateListChanged();
}

QString VideoPlateDetectService::resolveBackendRoot() const
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

QString VideoPlateDetectService::toLocalFileUrl(const QString &relativePath) const
{
    const QString backendRoot = resolveBackendRoot();
    const QString absolutePath = QDir(backendRoot).filePath(relativePath);
    return QUrl::fromLocalFile(absolutePath).toString();
}

void VideoPlateDetectService::cancelActiveRequest()
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

bool VideoPlateDetectService::prepareUpload(const QUrl &sourceVideoUrl, QString *destPath)
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
    *destPath = QDir(uploadDirPath).filePath(sourceInfo.fileName());

    if (QFile::exists(*destPath))
        QFile::remove(*destPath);

    if (!QFile::copy(sourcePath, *destPath)) {
        setErrorMessage(tr("复制视频到后端目录失败：%1").arg(*destPath));
        return false;
    }

    return true;
}

/// 构造 plate 检测的 multipart（只需 file，可选 frame_interval）
static QHttpMultiPart *createPlateMultipart(const QString &destPath, bool includeFrameInterval)
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
    const QString mimeType = QMimeDatabase().mimeTypeForFile(destPath).name();
    filePart.setHeader(QNetworkRequest::ContentTypeHeader, mimeType);
    filePart.setBodyDevice(file);
    file->setParent(multiPart);
    multiPart->append(filePart);

    if (includeFrameInterval) {
        QHttpPart intervalPart;
        intervalPart.setHeader(QNetworkRequest::ContentDispositionHeader,
                               QVariant(QStringLiteral("form-data; name=\"frame_interval\"")));
        intervalPart.setBody(QByteArray::number(kFrameInterval));
        multiPart->append(intervalPart);
    }

    return multiPart;
}

/// 解析 plate_list JSON 数组 → QVariantList
static QVariantList parsePlateList(const QJsonArray &plateArray)
{
    QVariantList plates;
    for (const auto &item : plateArray) {
        const QJsonObject obj = item.toObject();
        QVariantMap map;
        map[QStringLiteral("plateno")] = obj.value(QStringLiteral("plateno")).toString();
        map[QStringLiteral("platecolor")] = obj.value(QStringLiteral("platecolor")).toString();
        map[QStringLiteral("city")] = obj.value(QStringLiteral("city")).toString();
        plates.append(map);
    }
    return plates;
}

void VideoPlateDetectService::detect(const QUrl &sourceVideoUrl, bool realtimeDetect)
{
    if (m_busy) return;

    cancelActiveRequest();

    setErrorMessage({});
    setResultVideoUrl({});
    setDetectionCount(0);
    setStatusMessage({});
    setPlateList({});
    setRealtimeDetect(realtimeDetect);
    m_streamTotalFrames = 0;
    m_streamFps = 25;
    m_streamBuffer.clear();
    m_statusUpdateCounter = 0;
    m_lastDisplayedFrameIndex = -1;
    ++m_decodeJobId;

    QString destPath;
    if (!prepareUpload(sourceVideoUrl, &destPath)) {
        emit detectFinished(false);
        return;
    }

    setBusy(true);

    if (realtimeDetect)
        startStreamDetect(destPath);
    else
        startBatchDetect(destPath);
}

bool VideoPlateDetectService::openResultVideoWithSystemPlayer()
{
    if (m_busy || m_resultVideoUrl.isEmpty()) return false;

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

void VideoPlateDetectService::cancelDetect()
{
    if (!m_busy) return;
    setBusy(false);
    cancelActiveRequest();
    setStatusMessage({});
    emit detectFinished(false);
}

void VideoPlateDetectService::startBatchDetect(const QString &destPath)
{
    setStatusMessage(tr("正在检测，请稍候..."));

    auto *multiPart = createPlateMultipart(destPath, false);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传视频：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kBatchEndpoint)));
    request.setTransferTimeout(kVideoRequestTimeoutMs);
    m_activeReply = m_networkManager->post(request, multiPart);
    multiPart->setParent(m_activeReply);

    connect(m_activeReply, &QNetworkReply::finished, this, [this]() {
        handleBatchReply(m_activeReply);
        m_activeReply->deleteLater();
        m_activeReply = nullptr;
    });
}

void VideoPlateDetectService::startStreamDetect(const QString &destPath)
{
    setStatusMessage(tr("实时检测中，请稍候..."));

    auto *multiPart = createPlateMultipart(destPath, true);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传视频：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kStreamEndpoint)));
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
            finishDetectFailed(tr("实时检测连接意外结束"));

        m_activeReply->deleteLater();
        m_activeReply = nullptr;
    });
}

void VideoPlateDetectService::appendStreamData(const QByteArray &chunk)
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

void VideoPlateDetectService::handleStreamLine(const QByteArray &line)
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
        finishDetectFailed(message.isEmpty() ? tr("实时检测失败") : message);
        return;
    }

    if (event == QLatin1String("start")) {
        m_streamTotalFrames = data.value(QStringLiteral("total_frames")).toInt(0);
        m_streamFps = qBound(1, data.value(QStringLiteral("fps")).toInt(25), 60);
        setStatusMessage(tr("实时检测中：共 %1 帧").arg(m_streamTotalFrames));
        return;
    }

    if (event == QLatin1String("done")) {
        const QString relativeUrl = data.value(QStringLiteral("url")).toString();
        const int plateNumber = data.value(QStringLiteral("plate_number")).toInt(0);
        const QJsonArray plateArray = data.value(QStringLiteral("plate_list")).toArray();

        const QString backendRoot = resolveBackendRoot();
        const QString absoluteResultPath = QDir(backendRoot).filePath(relativeUrl);
        if (!QFileInfo::exists(absoluteResultPath)) {
            finishDetectFailed(tr("检测结果视频不存在：%1").arg(absoluteResultPath));
            return;
        }

        setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
        setDetectionCount(plateNumber);
        setPlateList(parsePlateList(plateArray));

        if (plateNumber > 0)
            setStatusMessage(tr("检测完成，共识别 %1 个车牌").arg(plateNumber));
        else
            setStatusMessage(tr("检测完成，未识别到车牌"));

        setErrorMessage({});
        finishDetectSuccess();
        if (m_activeReply)
            m_activeReply->abort();
    }
}

void VideoPlateDetectService::scheduleFrameDecode(QByteArray line)
{
    const int jobId = m_decodeJobId.fetchAndAddAcquire(1) + 1;

    (void)QtConcurrent::run([this, line = std::move(line), jobId]() mutable {
        const DecodedStreamFrame decoded = decodeStreamFrameLine(line);
        if (!decoded.valid) return;

        QMetaObject::invokeMethod(
            this,
            [this, jobId, decoded]() {
                if (jobId != m_decodeJobId.loadAcquire()) return;
                if (decoded.frameIndex < m_lastDisplayedFrameIndex) return;

                m_lastDisplayedFrameIndex = decoded.frameIndex;
                publishFrame(decoded.frameIndex, decoded.image);

                ++m_statusUpdateCounter;
                if (m_statusUpdateCounter % kStatusUpdateEveryNFrames == 0) {
                    if (m_streamTotalFrames > 0)
                        setStatusMessage(tr("实时检测中：第 %1 / %2 帧")
                                             .arg(decoded.frameIndex + 1)
                                             .arg(m_streamTotalFrames));
                    else
                        setStatusMessage(tr("实时检测中：第 %1 帧").arg(decoded.frameIndex + 1));
                }
            },
            Qt::QueuedConnection);
    });
}

void VideoPlateDetectService::publishFrame(int frameIndex, const QImage &image)
{
    if (s_frameImageProvider)
        s_frameImageProvider->setFrame(frameIndex, image);

    const QString frameUrl = QStringLiteral("image://%1/%2")
                                 .arg(QLatin1String(StreamFrameImageProvider::kProviderId))
                                 .arg(frameIndex);
    emit frameDetected(frameIndex, frameUrl);
}

void VideoPlateDetectService::finishDetectFailed(const QString &message)
{
    if (!m_busy) return;
    cancelActiveRequest();
    setBusy(false);
    setErrorMessage(message);
    setStatusMessage({});
    emit detectFinished(false);
}

void VideoPlateDetectService::finishDetectSuccess()
{
    if (!m_busy) return;
    setBusy(false);
    emit detectFinished(true);
}

void VideoPlateDetectService::handleBatchReply(QNetworkReply *reply)
{
    setBusy(false);

    if (reply->error() != QNetworkReply::NoError) {
        setErrorMessage(tr("网络请求失败：%1").arg(reply->errorString()));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QJsonDocument document = QJsonDocument::fromJson(reply->readAll());
    if (!document.isObject()) {
        setErrorMessage(tr("后端返回数据格式错误"));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QJsonObject root = document.object();
    const int code = root.value(QStringLiteral("code")).toInt(-1);
    const QString message = root.value(QStringLiteral("msg")).toString();

    if (code != 200) {
        setErrorMessage(message.isEmpty() ? tr("检测失败") : message);
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QJsonObject data = root.value(QStringLiteral("data")).toObject();
    const QString relativeUrl = data.value(QStringLiteral("url")).toString();
    const int plateNumber = data.value(QStringLiteral("plate_number")).toInt(0);
    const QJsonArray plateArray = data.value(QStringLiteral("plate_list")).toArray();

    const QString backendRoot = resolveBackendRoot();
    const QString absoluteResultPath = QDir(backendRoot).filePath(relativeUrl);
    if (!QFileInfo::exists(absoluteResultPath)) {
        setErrorMessage(tr("检测结果视频不存在：%1").arg(absoluteResultPath));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
    setDetectionCount(plateNumber);
    setPlateList(parsePlateList(plateArray));

    if (plateNumber > 0)
        setStatusMessage(tr("检测完成，共识别 %1 个车牌").arg(plateNumber));
    else
        setStatusMessage(tr("检测完成，未识别到车牌"));

    setErrorMessage({});
    emit detectFinished(true);
}
