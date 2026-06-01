/**
 * @file ImageCarPersonDetectedService.cpp
 * @brief ImageCarPersonDetectedService 的实现：文件复制、HTTP 请求与 JSON 解析
 */

#include "ImageCarPersonDetectService.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHttpMultiPart>
#include <QHttpPart>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QHash>
#include <QMimeDatabase>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUuid>

namespace {
/** @brief Python FastAPI 后端基地址（与 backend/main.py 中 uvicorn 端口一致） */
constexpr auto kApiBaseUrl = "http://127.0.0.1:8000";
/** @brief 图片目标检测 REST 路径 */
constexpr auto kDetectEndpoint = "/yoloDetected";
}

/**
 * @brief 构造函数：创建网络管理器并绑定到 this 作为 parent
 * @param parent 父对象指针，可为 nullptr
 *
 * m_networkManager 的生命周期由 Qt 父子对象机制管理，无需手动 delete。
 */
ImageCarPersonDetectService::ImageCarPersonDetectService(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
{
}

/** @brief 析构函数，使用默认实现即可 */
ImageCarPersonDetectService::~ImageCarPersonDetectService() = default;

/**
 * @brief 读取 busy 属性
 * @return true 表示正在等待后端 HTTP 响应；false 表示空闲
 */
bool ImageCarPersonDetectService::busy() const
{
    return m_busy;
}

/**
 * @brief 读取 errorMessage 属性
 * @return 错误描述字符串，无错误时为空
 */
QString ImageCarPersonDetectService::errorMessage() const
{
    return m_errorMessage;
}

/**
 * @brief 读取 resultImageUrl 属性
 * @return 结果图的 file:// URL，未检测成功时为空
 */
QString ImageCarPersonDetectService::resultImageUrl() const
{
    return m_resultImageUrl;
}

/**
 * @brief 读取 detectionCount 属性
 * @return 后端返回的检测目标数量，默认 0
 */
int ImageCarPersonDetectService::detectionCount() const
{
    return m_detectionCount;
}

/**
 * @brief 读取 statusMessage 属性
 * @return 状态提示，如「正在检测…」或「检测完成：模型 …」
 */
QString ImageCarPersonDetectService::statusMessage() const
{
    return m_statusMessage;
}

/**
 * @brief 更新 busy 状态
 * @param busy 新的 busy 值
 *
 * 仅当值发生变化时才写入并 emit busyChanged()，避免 QML 多余刷新。
 */
void ImageCarPersonDetectService::setBusy(bool busy)
{
    if (m_busy == busy)
        return;
    m_busy = busy;
    emit busyChanged();
}

/**
 * @brief 更新 errorMessage
 * @param message 错误文本，传 {} 表示清空
 */
void ImageCarPersonDetectService::setErrorMessage(const QString &message)
{
    if (m_errorMessage == message)
        return;
    m_errorMessage = message;
    emit errorMessageChanged();
}

/**
 * @brief 更新 resultImageUrl
 * @param url 结果图 file:// URL
 */
void ImageCarPersonDetectService::setResultImageUrl(const QString &url)
{
    if (m_resultImageUrl == url)
        return;
    m_resultImageUrl = url;
    emit resultImageUrlChanged();
}

/**
 * @brief 更新 detectionCount
 * @param count 检测数量
 */
void ImageCarPersonDetectService::setDetectionCount(int count)
{
    if (m_detectionCount == count)
        return;
    m_detectionCount = count;
    emit detectionCountChanged();
}

/**
 * @brief 更新 statusMessage
 * @param message 状态描述文本
 */
void ImageCarPersonDetectService::setStatusMessage(const QString &message)
{
    if (m_statusMessage == message)
        return;
    m_statusMessage = message;
    emit statusMessageChanged();
}

/**
 * @brief 自动定位 backend 项目根目录
 * @return backend 绝对路径（目录内应存在 main.py）
 *
 * 查找策略：
 * 1. 从 QCoreApplication::applicationDirPath()（通常是 build/.../Debug）向上最多 6 层；
 * 2. 每层检查是否存在 backend/main.py；
 * 3. 若均未找到，回退到 applicationDirPath 下 ../../../backend（适配常见 Qt 构建目录结构）。
 */
QString ImageCarPersonDetectService::resolveBackendRoot() const
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

/**
 * @brief 界面中文标签 → 后端 YOLO class_name
 * @param targetLabel QML ComboBox 当前文本（中文）
 * @return 对应的英文类别名；不在映射表中则返回空字符串
 *
 * 「全部」映射为 all，后端会检测并标注所有类别。
 */
QString ImageCarPersonDetectService::mapTargetToClassName(const QString &targetLabel) const
{
    static const QHash<QString, QString> mapping = {
                                                    {QStringLiteral("全部"), QStringLiteral("all")},
                                                    {QStringLiteral("行人"), QStringLiteral("person")},
                                                    {QStringLiteral("汽车"), QStringLiteral("car")},
                                                    {QStringLiteral("自行车"), QStringLiteral("bicycle")},
                                                    {QStringLiteral("摩托车"), QStringLiteral("motorcycle")},
                                                    {QStringLiteral("公交车"), QStringLiteral("bus")},
                                                    {QStringLiteral("交通信号灯"), QStringLiteral("traffic light")},
                                                    };

    return mapping.value(targetLabel);
}

/**
 * @brief 执行完整的图片检测流程（供 QML 调用）
 * @param sourceImageUrl 源图片 QUrl（来自 FileDialog）
 * @param modelType      模型名，对应后端 model_type 表单字段
 * @param targetLabel    中文检测目标，内部会 mapTargetToClassName 转换
 *
 * 流程概要：
 * 1. 校验非 busy、源文件存在、目标可映射；
 * 2. 复制图片到 backend/upload/source/{uuid}/{filename}；
 * 3. 构造 multipart：file、class_name、model_type；
 * 4. 异步 POST 到 kApiBaseUrl + kDetectEndpoint；
 * 5. finished 回调中由 handleNetworkReply 解析结果。
 *
 * 无返回值；结束时 emit detectFinished(true/false)。
 */
void ImageCarPersonDetectService::detect(const QUrl &sourceImageUrl,
                                         const QString &modelType,
                                         const QString &targetLabel)
{
    // 防止重复点击导致并发请求
    if (m_busy)
        return;

    // 清空上一次检测结果
    setErrorMessage({});
    setResultImageUrl({});
    setDetectionCount(0);
    setStatusMessage({});

    // QUrl → 本地文件系统路径
    const QString sourcePath = sourceImageUrl.isLocalFile()
                                   ? sourceImageUrl.toLocalFile()
                                   : sourceImageUrl.toString(QUrl::PreferLocalFile);

    if (sourcePath.isEmpty() || !QFileInfo::exists(sourcePath)) {
        setErrorMessage(tr("请先上传有效的图片文件"));
        emit detectFinished(false);
        return;
    }

    const QString className = mapTargetToClassName(targetLabel);
    if (className.isEmpty()) {
        setErrorMessage(tr("不支持的检测目标：%1").arg(targetLabel));
        emit detectFinished(false);
        return;
    }

    // 记录中文标签，成功提示时使用（比后端英文 class_name 更友好）
    m_lastTargetLabel = targetLabel;

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

    // ---------- 构建 multipart/form-data 请求体 ----------
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

    // part 1: file（图片二进制）
    QHttpPart filePart;
    filePart.setHeader(QNetworkRequest::ContentDispositionHeader,
                       QVariant(QStringLiteral("form-data; name=\"file\"; filename=\"%1\"")
                                    .arg(QFileInfo(destPath).fileName())));
    const QString mimeType = QMimeDatabase().mimeTypeForFile(destPath).name();
    filePart.setHeader(QNetworkRequest::ContentTypeHeader, mimeType);
    filePart.setBodyDevice(file);
    file->setParent(multiPart);
    multiPart->append(filePart);

    // part 2: class_name（YOLO 类别）
    QHttpPart classPart;
    classPart.setHeader(QNetworkRequest::ContentDispositionHeader,
                        QVariant(QStringLiteral("form-data; name=\"class_name\"")));
    classPart.setBody(className.toUtf8());
    multiPart->append(classPart);

    // part 3: model_type（模型类型）
    QHttpPart modelPart;
    modelPart.setHeader(QNetworkRequest::ContentDispositionHeader,
                        QVariant(QStringLiteral("form-data; name=\"model_type\"")));
    modelPart.setBody(modelType.toUtf8());
    multiPart->append(modelPart);

    // ---------- 发送异步 POST ----------
    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kDetectEndpoint)));
    QNetworkReply *reply = m_networkManager->post(request, multiPart);
    multiPart->setParent(reply); // reply 销毁时一并释放 multiPart 与 file

    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        handleNetworkReply(reply);
        reply->deleteLater();
    });
}

/**
 * @brief 解析 /yoloDetected 的 HTTP 响应
 * @param reply 已完成的 QNetworkReply 指针
 *
 * 期望 JSON 结构：
 * {
 *   "code": 200,
 *   "msg": "Success",
 *   "data": {
 *     "numbers": 3,
 *     "class_name": "car",
 *     "model_type": "yolov8n",
 *     "url": "upload/detected/{uuid}/yolo_xxx.jpg"
 *   }
 * }
 *
 * 成功时：
 * - resultImageUrl ← backendRoot + data.url 转为 file://
 * - detectionCount ← data.numbers
 * - statusMessage  ← 中文摘要
 * - emit detectFinished(true)
 *
 * 失败时设置 errorMessage 并 emit detectFinished(false)。
 * 无返回值。
 */
void ImageCarPersonDetectService::handleNetworkReply(QNetworkReply *reply)
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
    const int numbers = data.value(QStringLiteral("numbers")).toInt(0);
    const QString className = data.value(QStringLiteral("class_name")).toString();
    const QString modelType = data.value(QStringLiteral("model_type")).toString();
    Q_UNUSED(className); // 成功提示使用 m_lastTargetLabel（中文）

    const QString backendRoot = resolveBackendRoot();
    const QString absoluteResultPath = QDir(backendRoot).filePath(relativeUrl);
    if (!QFileInfo::exists(absoluteResultPath)) {
        setErrorMessage(tr("检测结果图片不存在：%1").arg(absoluteResultPath));
        setStatusMessage({});
        emit detectFinished(false);
        return;
    }

    const QString resultUrl = QUrl::fromLocalFile(absoluteResultPath).toString();
    setResultImageUrl(resultUrl);
    setDetectionCount(numbers);
    setStatusMessage(tr("检测完成：模型 %1，目标：%2，数量：%3")
                         .arg(modelType, m_lastTargetLabel)
                         .arg(numbers));
    setErrorMessage({});
    emit detectFinished(true);
}

