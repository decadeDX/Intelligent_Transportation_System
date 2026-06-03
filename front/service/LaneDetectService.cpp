/**
 * @file LaneDetectService.cpp
 * @brief LaneDetectService 的实现
 */

#include "LaneDetectService.h"
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
constexpr auto kLineEndpoint = "/lineVideoDetected";
constexpr int kVideoRequestTimeoutMs = 600000;
constexpr int kFrameInterval = 1;
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

QHttpMultiPart *createLineDetectMultipart(const QString &destPath)
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

    QHttpPart intervalPart;
    intervalPart.setHeader(QNetworkRequest::ContentDispositionHeader,
                           QVariant(QStringLiteral("form-data; name=\"frame_interval\"")));
    intervalPart.setBody(QByteArray::number(kFrameInterval));
    multiPart->append(intervalPart);

    return multiPart;
}
}

StreamFrameImageProvider *LaneDetectService::s_frameImageProvider = nullptr;

void LaneDetectService::setFrameImageProvider(StreamFrameImageProvider *provider)
{
    s_frameImageProvider = provider;
}

LaneDetectService::LaneDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

LaneDetectService::~LaneDetectService()
{
    cancelActiveRequest();
}

bool LaneDetectService::busy() const
{
    return m_busy;
}

QString LaneDetectService::errorMessage() const
{
    return m_errorMessage;
}

QString LaneDetectService::resultVideoUrl() const
{
    return m_resultVideoUrl;
}

QString LaneDetectService::statusMessage() const
{
    return m_statusMessage;
}

QString LaneDetectService::rawJsonText() const
{
    return m_rawJsonText;
}

void LaneDetectService::setBusy(bool busy)
{
    if (m_busy == busy)
        return;
    m_busy = busy;
    emit busyChanged();
}

void LaneDetectService::setErrorMessage(const QString &message)
{
    if (m_errorMessage == message)
        return;
    m_errorMessage = message;
    emit errorMessageChanged();
}

void LaneDetectService::setResultVideoUrl(const QString &url)
{
    if (m_resultVideoUrl == url)
        return;
    m_resultVideoUrl = url;
    emit resultVideoUrlChanged();
}

void LaneDetectService::setStatusMessage(const QString &message)
{
    if (m_statusMessage == message)
        return;
    m_statusMessage = message;
    emit statusMessageChanged();
}

void LaneDetectService::setRawJsonText(const QString &text)
{
    if (m_rawJsonText == text)
        return;
    m_rawJsonText = text;
    emit rawJsonTextChanged();
}

void LaneDetectService::setRawJsonFromObject(const QJsonObject &object)
{
    setRawJsonText(QString::fromUtf8(QJsonDocument(object).toJson(QJsonDocument::Indented)));
}

QString LaneDetectService::resolveBackendRoot() const
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

QUrl LaneDetectService::resolveBackendResourceUrl(const QString &relativePath) const
{
    if (relativePath.isEmpty())
        return QUrl();

    const QString backendRoot = resolveBackendRoot();
    const QString fileName = QFileInfo(relativePath).fileName();

    const QStringList candidates = {
        QDir(backendRoot).filePath(QStringLiteral("../") + relativePath),
        QDir(backendRoot).filePath(relativePath),
        QDir(backendRoot).filePath(QStringLiteral("videos/") + fileName),
    };

    for (const QString &candidate : candidates) {
        const QString absolutePath = QDir::cleanPath(candidate);
        if (QFileInfo::exists(absolutePath))
            return QUrl::fromLocalFile(QFileInfo(absolutePath).absoluteFilePath());
    }

    return QUrl();
}

void LaneDetectService::cancelActiveRequest()
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

bool LaneDetectService::prepareUpload(const QUrl &sourceVideoUrl, UploadContext *ctx)
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
    const QString destPath = QDir(uploadDirPath).filePath(sourceInfo.fileName());

    if (QFile::exists(destPath))
        QFile::remove(destPath);

    if (!QFile::copy(sourcePath, destPath)) {
        setErrorMessage(tr("复制视频到后端目录失败：%1").arg(destPath));
        return false;
    }

    ctx->destPath = destPath;
    return true;
}

void LaneDetectService::detect(const QUrl &sourceVideoUrl)
{
    if (m_busy)
        return;

    cancelActiveRequest();

    setErrorMessage({});
    setResultVideoUrl({});
    setStatusMessage({});
    setRawJsonText({});
    m_streamTotalFrames = 0;
    m_streamBuffer.clear();
    m_statusUpdateCounter = 0;
    m_lastDisplayedFrameIndex = -1;
    ++m_decodeJobId;

    UploadContext ctx;
    if (!prepareUpload(sourceVideoUrl, &ctx)) {
        emit detectFinished(false);
        return;
    }

    setBusy(true);
    startStreamDetect(ctx);
}

bool LaneDetectService::openResultVideoWithSystemPlayer()
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

void LaneDetectService::cancelDetect()
{
    if (!m_busy)
        return;

    setBusy(false);
    cancelActiveRequest();
    setStatusMessage({});
    emit detectFinished(false);
}

void LaneDetectService::resetForCleanup()
{
    cancelActiveRequest();
    setBusy(false);
    setErrorMessage({});
    setResultVideoUrl({});
    setStatusMessage({});
    setRawJsonText({});
}

void LaneDetectService::clearResultMedia()
{
    setResultVideoUrl({});
}

void LaneDetectService::startStreamDetect(const UploadContext &ctx)
{
    setStatusMessage(tr("逐帧检测中，请稍候..."));

    auto *multiPart = createLineDetectMultipart(ctx.destPath);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传视频：%1").arg(ctx.destPath));
        emit detectFinished(false);
        return;
    }

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kLineEndpoint)));
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

        if (m_busy && m_activeReply->error() != QNetworkReply::NoError) {
            finishDetectFailed(tr("网络请求失败：%1").arg(m_activeReply->errorString()));
        } else if (m_busy) {
            finishDetectFailed(tr("检测连接意外结束"));
        }

        m_activeReply->deleteLater();
        m_activeReply = nullptr;
    });
}

void LaneDetectService::appendStreamData(const QByteArray &chunk)
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

void LaneDetectService::handleStreamLine(const QByteArray &line)
{
    if (line.startsWith("{\"event\":\"frame\"") || line.startsWith("{\"event\": \"frame\"")) {
        scheduleFrameDecode(line);
        return;
    }

    const QJsonDocument document = QJsonDocument::fromJson(line);
    if (!document.isObject())
        return;

    const QJsonObject root = document.object();
    const QString event = root.value(QStringLiteral("event")).toString();
    const int code = root.value(QStringLiteral("code")).toInt(-1);
    const QString message = root.value(QStringLiteral("msg")).toString();
    const QJsonObject data = root.value(QStringLiteral("data")).toObject();

    if (event == QLatin1String("error") || code != 200) {
        setRawJsonFromObject(root);
        finishDetectFailed(message.isEmpty() ? tr("检测失败") : message);
        return;
    }

    if (event == QLatin1String("start")) {
        m_streamTotalFrames = data.value(QStringLiteral("total_frames")).toInt(0);
        setStatusMessage(tr("逐帧检测中：共 %1 帧").arg(m_streamTotalFrames));
        return;
    }

    if (event == QLatin1String("done")) {
        setRawJsonFromObject(root);

        const QString relativeUrl = data.value(QStringLiteral("url")).toString();
        const int processedFrames = data.value(QStringLiteral("processed_frames")).toInt(0);
        const int framesWithLane = data.value(QStringLiteral("frames_with_lane")).toInt(0);
        const int vehicleTotal = data.value(QStringLiteral("vehicle_count_total")).toInt(0);

        const QString backendRoot = resolveBackendRoot();
        const QString absoluteResultPath = QDir(backendRoot).filePath(relativeUrl);
        if (!QFileInfo::exists(absoluteResultPath)) {
            finishDetectFailed(tr("检测结果视频不存在：%1").arg(absoluteResultPath));
            return;
        }

        setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
        setStatusMessage(tr("检测完成：共 %1 帧，含车道 %2 帧，车辆检测 %3 次")
                             .arg(processedFrames)
                             .arg(framesWithLane)
                             .arg(vehicleTotal));
        setErrorMessage({});
        finishDetectSuccess();
        if (m_activeReply)
            m_activeReply->abort();
    }
}

void LaneDetectService::scheduleFrameDecode(QByteArray line)
{
    const int jobId = m_decodeJobId.fetchAndAddAcquire(1) + 1;

    (void)QtConcurrent::run([this, line = std::move(line), jobId]() mutable {
        const DecodedStreamFrame decoded = decodeStreamFrameLine(line);
        if (!decoded.valid)
            return;

        QMetaObject::invokeMethod(
            this,
            [this, jobId, decoded]() {
                if (jobId != m_decodeJobId.loadAcquire())
                    return;
                if (decoded.frameIndex < m_lastDisplayedFrameIndex)
                    return;

                m_lastDisplayedFrameIndex = decoded.frameIndex;
                publishFrame(decoded.frameIndex, decoded.image);

                ++m_statusUpdateCounter;
                if (m_statusUpdateCounter % kStatusUpdateEveryNFrames == 0) {
                    if (m_streamTotalFrames > 0) {
                        setStatusMessage(tr("逐帧检测中：第 %1 / %2 帧")
                                             .arg(decoded.frameIndex + 1)
                                             .arg(m_streamTotalFrames));
                    } else {
                        setStatusMessage(tr("逐帧检测中：第 %1 帧").arg(decoded.frameIndex + 1));
                    }
                }
            },
            Qt::QueuedConnection);
    });
}

void LaneDetectService::publishFrame(int frameIndex, const QImage &image)
{
    if (s_frameImageProvider)
        s_frameImageProvider->setFrame(frameIndex, image);

    const QString frameUrl = QStringLiteral("image://%1/%2")
                                 .arg(QLatin1String(StreamFrameImageProvider::kProviderId))
                                 .arg(frameIndex);
    emit frameDetected(frameIndex, frameUrl);
}

void LaneDetectService::finishDetectFailed(const QString &message)
{
    if (!m_busy)
        return;

    cancelActiveRequest();
    setBusy(false);
    setErrorMessage(message);
    setStatusMessage({});
    emit detectFinished(false);
}

void LaneDetectService::finishDetectSuccess()
{
    if (!m_busy)
        return;

    setBusy(false);
    emit detectFinished(true);
}
