#include "ImagePlateDetectService.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHttpMultiPart>
#include <QHttpPart>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMimeDatabase>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUuid>

namespace {
constexpr auto kApiBaseUrl = "http://127.0.0.1:8000";
constexpr auto kDetectEndpoint = "/plateDetected";
}

ImagePlateDetectService::ImagePlateDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

ImagePlateDetectService::~ImagePlateDetectService() = default;

bool ImagePlateDetectService::busy() const { return m_busy; }
QString ImagePlateDetectService::errorMessage() const { return m_errorMessage; }
QString ImagePlateDetectService::resultImageUrl() const { return m_resultImageUrl; }
int ImagePlateDetectService::detectionCount() const { return m_detectionCount; }
QString ImagePlateDetectService::statusMessage() const { return m_statusMessage; }
QVariantList ImagePlateDetectService::plateList() const { return m_plateList; }

void ImagePlateDetectService::setBusy(bool v)
{
    if (m_busy == v) return;
    m_busy = v;
    emit busyChanged();
}

void ImagePlateDetectService::setErrorMessage(const QString &v)
{
    if (m_errorMessage == v) return;
    m_errorMessage = v;
    emit errorMessageChanged();
}

void ImagePlateDetectService::setResultImageUrl(const QString &v)
{
    if (m_resultImageUrl == v) return;
    m_resultImageUrl = v;
    emit resultImageUrlChanged();
}

void ImagePlateDetectService::setDetectionCount(int v)
{
    if (m_detectionCount == v) return;
    m_detectionCount = v;
    emit detectionCountChanged();
}

void ImagePlateDetectService::setStatusMessage(const QString &v)
{
    if (m_statusMessage == v) return;
    m_statusMessage = v;
    emit statusMessageChanged();
}

void ImagePlateDetectService::setPlateList(const QVariantList &v)
{
    if (m_plateList == v) return;
    m_plateList = v;
    emit plateListChanged();
}

QString ImagePlateDetectService::resolveBackendRoot() const
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

void ImagePlateDetectService::detect(const QUrl &sourceImageUrl)
{
    if (m_busy) return;

    setErrorMessage({});
    setResultImageUrl({});
    setDetectionCount(0);
    setStatusMessage({});
    setPlateList({});

    const QString sourcePath = sourceImageUrl.isLocalFile()
                                   ? sourceImageUrl.toLocalFile()
                                   : sourceImageUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的图片文件"));
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

    if (QFile::exists(destPath))
        QFile::remove(destPath);

    if (!QFile::copy(sourcePath, destPath)) {
        setErrorMessage(tr("复制图片到后端目录失败：%1").arg(destPath));
        emit detectFinished(false);
        return;
    }

    setBusy(true);
    setStatusMessage(tr("正在检测，请稍候..."));

    // 构建 multipart/form-data —— 车牌接口只需要 file 一个字段
    auto *multiPart = new QHttpMultiPart(QHttpMultiPart::FormDataType);

    auto *file = new QFile(destPath);
    if (!file->open(QIODevice::ReadOnly)) {
        setBusy(false);
        setErrorMessage(tr("无法读取上传图片：%1").arg(destPath));
        delete file;
        delete multiPart;
        emit detectFinished(false);
        return;
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

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kDetectEndpoint)));
    QNetworkReply *reply = m_networkManager->post(request, multiPart);
    multiPart->setParent(reply);

    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        handleNetworkReply(reply);
        reply->deleteLater();
    });
}

void ImagePlateDetectService::handleNetworkReply(QNetworkReply *reply)
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

    const QString backendRoot = resolveBackendRoot();
    const QString absoluteResultPath = QDir(backendRoot).filePath(relativeUrl);
    if (!QFileInfo::exists(absoluteResultPath)) {
        setErrorMessage(tr("检测结果图片不存在：%1").arg(absoluteResultPath));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    // 解析 plate_list → QVariantList
    const QJsonArray plateArray = data.value(QStringLiteral("plate_list")).toArray();
    QVariantList plates;
    for (const auto &item : plateArray) {
        const QJsonObject obj = item.toObject();
        QVariantMap map;
        map[QStringLiteral("plateno")] = obj.value(QStringLiteral("plateno")).toString();
        map[QStringLiteral("platecolor")] = obj.value(QStringLiteral("platecolor")).toString();
        map[QStringLiteral("city")] = obj.value(QStringLiteral("city")).toString();
        plates.append(map);
    }

    const QString resultUrl = QUrl::fromLocalFile(absoluteResultPath).toString();
    setResultImageUrl(resultUrl);
    setDetectionCount(plateNumber);
    setPlateList(plates);

    if (plateNumber > 0)
        setStatusMessage(tr("检测完成，共识别 %1 个车牌").arg(plateNumber));
    else
        setStatusMessage(tr("检测完成，未识别到车牌"));

    setErrorMessage({});
    emit detectFinished(true);
}
