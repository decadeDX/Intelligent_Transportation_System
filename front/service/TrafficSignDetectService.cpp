#include "TrafficSignDetectService.h"
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
#include <QVariantMap>
#include <QtConcurrent/QtConcurrent>

namespace {
constexpr auto kApiBaseUrl = "http://127.0.0.1:8000";
constexpr auto kImageEndpoint = "/signDetected";
constexpr auto kVideoEndpoint = "/signVideoDetectedWithFrame";
constexpr int kRequestTimeoutMs = 600000;
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

QVariantList detectionsToVariantList(const QJsonArray &detections)
{
    QVariantList list;
    for (const QJsonValue &value : detections) {
        const QJsonObject obj = value.toObject();
        QVariantMap item;
        item[QStringLiteral("class_name")] = obj.value(QStringLiteral("class_name")).toString();
        item[QStringLiteral("confidence")] = obj.value(QStringLiteral("confidence")).toDouble(0.0);
        item[QStringLiteral("class_id")] = obj.value(QStringLiteral("class_id")).toInt(-1);
        item[QStringLiteral("x1")] = obj.value(QStringLiteral("x1")).toInt(0);
        item[QStringLiteral("y1")] = obj.value(QStringLiteral("y1")).toInt(0);
        item[QStringLiteral("x2")] = obj.value(QStringLiteral("x2")).toInt(0);
        item[QStringLiteral("y2")] = obj.value(QStringLiteral("y2")).toInt(0);
        list.append(item);
    }
    return list;
}

QVariantList classCountsToVariantList(const QJsonObject &classCounts)
{
    QVariantList list;
    for (auto it = classCounts.constBegin(); it != classCounts.constEnd(); ++it) {
        QVariantMap item;
        item[QStringLiteral("class_name")] = it.key();
        item[QStringLiteral("count")] = it.value().toInt(0);
        item[QStringLiteral("confidence")] = 0.0;
        list.append(item);
    }
    return list;
}

void appendTextPart(QHttpMultiPart *multiPart, const QString &name, const QByteArray &value)
{
    QHttpPart part;
    part.setHeader(QNetworkRequest::ContentDispositionHeader,
                   QVariant(QStringLiteral("form-data; name=\"%1\"").arg(name)));
    part.setBody(value);
    multiPart->append(part);
}

QHttpMultiPart *createDetectMultipart(const QString &destPath, bool includeFrameInterval)
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

    if (includeFrameInterval)
        appendTextPart(multiPart, QStringLiteral("frame_interval"), QByteArray::number(kFrameInterval));

    return multiPart;
}
} // namespace

StreamFrameImageProvider *TrafficSignDetectService::s_frameImageProvider = nullptr;

void TrafficSignDetectService::setFrameImageProvider(StreamFrameImageProvider *provider)
{
    s_frameImageProvider = provider;
}

TrafficSignDetectService::TrafficSignDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

TrafficSignDetectService::~TrafficSignDetectService()
{
    cancelActiveRequest();
}

bool TrafficSignDetectService::busy() const { return m_busy; }
QString TrafficSignDetectService::errorMessage() const { return m_errorMessage; }
QString TrafficSignDetectService::resultVideoUrl() const { return m_resultVideoUrl; }
QString TrafficSignDetectService::resultImageUrl() const { return m_resultImageUrl; }
QString TrafficSignDetectService::statusMessage() const { return m_statusMessage; }
int TrafficSignDetectService::signCount() const { return m_signCount; }
int TrafficSignDetectService::uniqueSignTypes() const { return m_uniqueSignTypes; }
QVariantList TrafficSignDetectService::signList() const { return m_signList; }

void TrafficSignDetectService::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void TrafficSignDetectService::setErrorMessage(const QString &value)
{
    if (m_errorMessage == value)
        return;
    m_errorMessage = value;
    emit errorMessageChanged();
}

void TrafficSignDetectService::setResultVideoUrl(const QString &value)
{
    if (m_resultVideoUrl == value)
        return;
    m_resultVideoUrl = value;
    emit resultVideoUrlChanged();
}

void TrafficSignDetectService::setResultImageUrl(const QString &value)
{
    if (m_resultImageUrl == value)
        return;
    m_resultImageUrl = value;
    emit resultImageUrlChanged();
}

void TrafficSignDetectService::setStatusMessage(const QString &value)
{
    if (m_statusMessage == value)
        return;
    m_statusMessage = value;
    emit statusMessageChanged();
}

void TrafficSignDetectService::setSignCount(int value)
{
    if (m_signCount == value)
        return;
    m_signCount = value;
    emit signCountChanged();
}

void TrafficSignDetectService::setUniqueSignTypes(int value)
{
    if (m_uniqueSignTypes == value)
        return;
    m_uniqueSignTypes = value;
    emit uniqueSignTypesChanged();
}

void TrafficSignDetectService::setSignList(const QVariantList &value)
{
    if (m_signList == value)
        return;
    m_signList = value;
    emit signListChanged();
}

QString TrafficSignDetectService::resolveBackendRoot() const
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

void TrafficSignDetectService::resetResultState()
{
    setErrorMessage({});
    setResultVideoUrl({});
    setResultImageUrl({});
    setStatusMessage({});
    setSignCount(0);
    setUniqueSignTypes(0);
    setSignList({});
    m_streamTotalFrames = 0;
    m_statusUpdateCounter = 0;
    m_lastDisplayedFrameIndex = -1;
    m_streamBuffer.clear();
}

void TrafficSignDetectService::cancelActiveRequest()
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

bool TrafficSignDetectService::prepareUpload(const QUrl &sourceUrl, QString *destPath)
{
    const QString sourcePath = sourceUrl.isLocalFile()
                                   ? sourceUrl.toLocalFile()
                                   : sourceUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的文件"));
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
        setErrorMessage(tr("复制文件到后端目录失败：%1").arg(targetPath));
        return false;
    }

    *destPath = targetPath;
    return true;
}

void TrafficSignDetectService::detect(const QUrl &sourceUrl, int mediaType)
{
    if (m_busy)
        return;

    cancelActiveRequest();
    resetResultState();
    m_mode = mediaType == 0 ? MediaMode::Image : MediaMode::Video;
    ++m_decodeJobId;

    QString destPath;
    if (!prepareUpload(sourceUrl, &destPath)) {
        emit detectFinished(false);
        return;
    }

    setBusy(true);
    if (m_mode == MediaMode::Image)
        startImageDetect(destPath);
    else
        startVideoDetect(destPath);
}

bool TrafficSignDetectService::openResultVideoWithSystemPlayer()
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

void TrafficSignDetectService::cancelDetect()
{
    if (!m_busy)
        return;

    setBusy(false);
    cancelActiveRequest();
    setStatusMessage({});
    emit detectFinished(false);
}

void TrafficSignDetectService::startImageDetect(const QString &destPath)
{
    setStatusMessage(tr("正在检测，请稍候..."));

    auto *multiPart = createDetectMultipart(destPath, false);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传图片：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kImageEndpoint)));
    request.setTransferTimeout(kRequestTimeoutMs);
    m_activeReply = m_networkManager->post(request, multiPart);
    multiPart->setParent(m_activeReply);

    connect(m_activeReply, &QNetworkReply::finished, this, [this]() {
        if (!m_activeReply)
            return;
        handleImageReply(m_activeReply);
        m_activeReply->deleteLater();
        m_activeReply = nullptr;
    });
}

void TrafficSignDetectService::startVideoDetect(const QString &destPath)
{
    setStatusMessage(tr("实时检测中，请稍候..."));

    auto *multiPart = createDetectMultipart(destPath, true);
    if (!multiPart) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传视频：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kVideoEndpoint)));
    request.setTransferTimeout(kRequestTimeoutMs);
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

void TrafficSignDetectService::handleImageReply(QNetworkReply *reply)
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
        setErrorMessage(message.isEmpty() ? tr("交通标识检测失败") : message);
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QJsonObject data = root.value(QStringLiteral("data")).toObject();
    const QString relativeUrl = data.value(QStringLiteral("url")).toString();
    const QString absoluteResultPath = QDir(resolveBackendRoot()).filePath(relativeUrl);
    if (!QFileInfo::exists(absoluteResultPath)) {
        setErrorMessage(tr("检测结果图片不存在：%1").arg(absoluteResultPath));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const int count = data.value(QStringLiteral("sign_count")).toInt(0);
    const int uniqueTypes = data.value(QStringLiteral("unique_sign_types")).toInt(0);
    setResultImageUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
    setSignCount(count);
    setUniqueSignTypes(uniqueTypes);
    setSignList(detectionsToVariantList(data.value(QStringLiteral("detections")).toArray()));
    setStatusMessage(tr("检测完成：发现 %1 个交通标识，%2 种类型").arg(count).arg(uniqueTypes));
    setErrorMessage({});
    emit detectFinished(true);
}

void TrafficSignDetectService::appendStreamData(const QByteArray &chunk)
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

void TrafficSignDetectService::handleStreamLine(const QByteArray &line)
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
        finishDetectFailed(message.isEmpty() ? tr("交通标识检测失败") : message);
        return;
    }

    if (event == QLatin1String("start")) {
        m_streamTotalFrames = data.value(QStringLiteral("total_frames")).toInt(0);
        setStatusMessage(tr("实时检测中：共 %1 帧").arg(m_streamTotalFrames));
        return;
    }

    if (event == QLatin1String("frame")) {
        const QJsonArray detections = data.value(QStringLiteral("detections")).toArray();
        setSignCount(data.value(QStringLiteral("sign_count")).toInt(detections.size()));
        setSignList(detectionsToVariantList(detections));
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

        const int totalSigns = data.value(QStringLiteral("total_signs_detected")).toInt(0);
        const int uniqueTypes = data.value(QStringLiteral("unique_sign_types")).toInt(0);
        const QJsonObject classCounts = data.value(QStringLiteral("sign_class_counts")).toObject();

        setResultVideoUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
        setSignCount(totalSigns);
        setUniqueSignTypes(uniqueTypes);
        setSignList(classCountsToVariantList(classCounts));
        setStatusMessage(tr("检测完成：累计发现 %1 个交通标识，%2 种类型")
                             .arg(totalSigns)
                             .arg(uniqueTypes));
        setErrorMessage({});
        finishDetectSuccess();
        if (m_activeReply)
            m_activeReply->abort();
    }
}

void TrafficSignDetectService::scheduleFrameDecode(QByteArray line)
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
                    setStatusMessage(tr("实时检测中：第 %1 / %2 帧")
                                         .arg(decoded.frameIndex + 1)
                                         .arg(m_streamTotalFrames));
                } else {
                    setStatusMessage(tr("实时检测中：第 %1 帧").arg(decoded.frameIndex + 1));
                }
            }
        }, Qt::QueuedConnection);
    });
}

void TrafficSignDetectService::publishFrame(int frameIndex, const QImage &image)
{
    if (s_frameImageProvider)
        s_frameImageProvider->setFrame(frameIndex, image);

    const QString frameUrl = QStringLiteral("image://%1/%2")
                                 .arg(QLatin1String(StreamFrameImageProvider::kProviderId))
                                 .arg(frameIndex);
    emit frameDetected(frameIndex, frameUrl);
}

void TrafficSignDetectService::finishDetectFailed(const QString &message)
{
    if (!m_busy)
        return;

    cancelActiveRequest();
    setBusy(false);
    setErrorMessage(message);
    setStatusMessage({});
    emit detectFinished(false);
}

void TrafficSignDetectService::finishDetectSuccess()
{
    if (!m_busy)
        return;

    setBusy(false);
    emit detectFinished(true);
}
