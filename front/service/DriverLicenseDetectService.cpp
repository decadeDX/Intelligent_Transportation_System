#include "DriverLicenseDetectService.h"

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
constexpr auto kDetectEndpoint = "/driverLicenseDetected";

QVariantList parseTextList(const QJsonArray &array)
{
    QVariantList items;
    for (const QJsonValue &value : array) {
        const QJsonObject obj = value.toObject();
        QVariantMap item;
        item[QStringLiteral("text")] = obj.value(QStringLiteral("text")).toString();
        item[QStringLiteral("confidence")] = obj.value(QStringLiteral("confidence")).toDouble(0.0);
        item[QStringLiteral("bbox")] = obj.value(QStringLiteral("bbox")).toArray().toVariantList();
        items.append(item);
    }
    return items;
}

QString dataString(const QJsonObject &data, const QString &key)
{
    return data.value(key).toString();
}

void appendTextPart(QHttpMultiPart *multiPart, const QString &name, const QByteArray &value)
{
    QHttpPart part;
    part.setHeader(QNetworkRequest::ContentDispositionHeader,
                   QVariant(QStringLiteral("form-data; name=\"%1\"").arg(name)));
    part.setBody(value);
    multiPart->append(part);
}
} // namespace

DriverLicenseDetectService::DriverLicenseDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

DriverLicenseDetectService::~DriverLicenseDetectService() = default;

bool DriverLicenseDetectService::busy() const { return m_busy; }
QString DriverLicenseDetectService::errorMessage() const { return m_errorMessage; }
QString DriverLicenseDetectService::resultImageUrl() const { return m_resultImageUrl; }
QString DriverLicenseDetectService::statusMessage() const { return m_statusMessage; }
int DriverLicenseDetectService::textNumber() const { return m_textNumber; }
QVariantMap DriverLicenseDetectService::licenseInfo() const { return m_licenseInfo; }
QVariantList DriverLicenseDetectService::textList() const { return m_textList; }
QString DriverLicenseDetectService::fullText() const { return m_fullText; }

void DriverLicenseDetectService::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void DriverLicenseDetectService::setErrorMessage(const QString &value)
{
    if (m_errorMessage == value)
        return;
    m_errorMessage = value;
    emit errorMessageChanged();
}

void DriverLicenseDetectService::setResultImageUrl(const QString &value)
{
    if (m_resultImageUrl == value)
        return;
    m_resultImageUrl = value;
    emit resultImageUrlChanged();
}

void DriverLicenseDetectService::setStatusMessage(const QString &value)
{
    if (m_statusMessage == value)
        return;
    m_statusMessage = value;
    emit statusMessageChanged();
}

void DriverLicenseDetectService::setTextNumber(int value)
{
    if (m_textNumber == value)
        return;
    m_textNumber = value;
    emit textNumberChanged();
}

void DriverLicenseDetectService::setLicenseInfo(const QVariantMap &value)
{
    if (m_licenseInfo == value)
        return;
    m_licenseInfo = value;
    emit licenseInfoChanged();
}

void DriverLicenseDetectService::setTextList(const QVariantList &value)
{
    if (m_textList == value)
        return;
    m_textList = value;
    emit textListChanged();
}

void DriverLicenseDetectService::setFullText(const QString &value)
{
    if (m_fullText == value)
        return;
    m_fullText = value;
    emit fullTextChanged();
}

QString DriverLicenseDetectService::resolveBackendRoot() const
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

void DriverLicenseDetectService::resetResultState()
{
    setErrorMessage({});
    setResultImageUrl({});
    setStatusMessage({});
    setTextNumber(0);
    setLicenseInfo({});
    setTextList({});
    setFullText({});
}

bool DriverLicenseDetectService::prepareUpload(const QUrl &sourceImageUrl, QString *destPath)
{
    const QString sourcePath = sourceImageUrl.isLocalFile()
                                   ? sourceImageUrl.toLocalFile()
                                   : sourceImageUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的图片文件"));
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
        setErrorMessage(tr("复制图片到后端目录失败：%1").arg(*destPath));
        return false;
    }

    return true;
}

void DriverLicenseDetectService::detect(const QUrl &sourceImageUrl, const QString &recognitionType)
{
    if (m_busy)
        return;

    resetResultState();

    QString destPath;
    if (!prepareUpload(sourceImageUrl, &destPath)) {
        emit detectFinished(false);
        return;
    }

    auto *multiPart = new QHttpMultiPart(QHttpMultiPart::FormDataType);
    auto *file = new QFile(destPath);
    if (!file->open(QIODevice::ReadOnly)) {
        delete file;
        delete multiPart;
        setErrorMessage(tr("无法读取上传图片：%1").arg(destPath));
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
    appendTextPart(multiPart,
                   QStringLiteral("recognition_type"),
                   recognitionType.toUtf8());

    setBusy(true);
    setStatusMessage(tr("正在识别，请稍候..."));

    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kDetectEndpoint)));
    QNetworkReply *reply = m_networkManager->post(request, multiPart);
    multiPart->setParent(reply);

    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        handleNetworkReply(reply);
        reply->deleteLater();
    });
}

void DriverLicenseDetectService::handleNetworkReply(QNetworkReply *reply)
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
        setErrorMessage(message.isEmpty() ? tr("驾驶证识别失败") : message);
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QJsonObject data = root.value(QStringLiteral("data")).toObject();
    const QString relativeUrl = data.value(QStringLiteral("url")).toString();
    const QString absoluteResultPath = QDir(resolveBackendRoot()).filePath(relativeUrl);
    if (!QFileInfo::exists(absoluteResultPath)) {
        setErrorMessage(tr("识别结果图片不存在：%1").arg(absoluteResultPath));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QJsonObject fields = data.value(QStringLiteral("structured_fields")).toObject(data);
    QVariantMap licenseInfo;
    licenseInfo[QStringLiteral("card_type")] = dataString(data, QStringLiteral("card_type"));
    licenseInfo[QStringLiteral("name")] = dataString(fields, QStringLiteral("name"));
    licenseInfo[QStringLiteral("gender")] = dataString(fields, QStringLiteral("gender"));
    licenseInfo[QStringLiteral("idno")] = dataString(fields, QStringLiteral("idno"));
    licenseInfo[QStringLiteral("address")] = dataString(fields, QStringLiteral("address"));
    licenseInfo[QStringLiteral("type")] = dataString(fields, QStringLiteral("type"));
    licenseInfo[QStringLiteral("nationality")] = dataString(fields, QStringLiteral("nationality"));
    licenseInfo[QStringLiteral("nation")] = dataString(fields, QStringLiteral("nation"));
    licenseInfo[QStringLiteral("first_issue_date")] = dataString(fields, QStringLiteral("first_issue_date"));
    licenseInfo[QStringLiteral("birth_date")] = dataString(fields, QStringLiteral("birth_date"));

    const int textNumber = data.value(QStringLiteral("text_number")).toInt(0);
    setResultImageUrl(QUrl::fromLocalFile(absoluteResultPath).toString());
    setTextNumber(textNumber);
    setLicenseInfo(licenseInfo);
    setTextList(parseTextList(data.value(QStringLiteral("text_list")).toArray()));
    setFullText(data.value(QStringLiteral("full_text")).toString());
    setStatusMessage(tr("识别完成，共识别 %1 条文本").arg(textNumber));
    setErrorMessage({});
    emit detectFinished(true);
}
