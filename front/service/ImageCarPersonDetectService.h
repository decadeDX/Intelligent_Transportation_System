/**
 * @file ImageCarPersonDetectService.h
 * @brief 图片车辆/行人检测业务服务类（供 QML 调用）
 *
 * 本类封装与 Python FastAPI 后端 /yoloDetected 接口的全部交互逻辑，包括：
 * - 将用户选择的本地图片复制到 backend/upload/source/{uuid}/
 * - 以 multipart/form-data 异步 POST 请求发起检测
 * - 解析 JSON 响应并更新 QML 可绑定的属性（结果图 URL、检测数量、状态/错误信息等）
 *
 * 对应 QML 界面：qml/ImageCarPersonDected.qml
 */

#ifndef IMAGECARPERSONDETECTSERVICE_H  // 头文件保护宏，防止重复包含
#define IMAGECARPERSONDETECTSERVICE_H

#include <QObject>           // Qt 对象基类，支持信号槽与属性系统
#include <QUrl>              // 统一表示本地/网络路径（FileDialog 返回 QUrl）
#include <qqmlintegration.h> // QML_ELEMENT 宏，用于自动注册到 QML 模块

class QNetworkAccessManager; // 前向声明：HTTP 网络管理器，负责异步 POST
class QNetworkReply;         // 前向声明：单次网络请求的响应对象

/**
 * @class ImageCarPersonDetectService
 * @brief 图片目标检测服务，暴露给 QML 的属性与方法均在此定义
 *
 * QML 侧通过 import front 后直接使用 ImageCarPersonDetectService { id: svc } 实例化，
 * 调用 svc.detect(...) 并在 onDetectFinished 中读取 svc.resultImageUrl 等属性。
 */
class ImageCarPersonDetectService : public QObject
{
    Q_OBJECT    // 启用 Qt 元对象系统（信号、槽、属性）
    QML_ELEMENT // 注册到 CMake qt_add_qml_module 的 URI（front）下，供 QML 使用

    /** @brief 是否正在请求后端（true 时 QML 应禁用按钮并显示 BusyIndicator） */
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    /** @brief 最近一次错误或校验失败的中文提示，空字符串表示无错误 */
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    /** @brief 检测结果图片的本地 file:// URL，供右侧 Image.source 绑定 */
    Q_PROPERTY(QString resultImageUrl READ resultImageUrl NOTIFY resultImageUrlChanged)
    /** @brief 后端返回的检测目标数量（numbers 字段） */
    Q_PROPERTY(int detectionCount READ detectionCount NOTIFY detectionCountChanged)
    /** @brief 检测过程/完成后的状态描述，显示在右侧结果图下方 */
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)

public:
    /**
     * @brief 构造函数
     * @param parent 父 QObject，通常由 QML 引擎管理生命周期
     */
    explicit ImageCarPersonDetectService(QObject *parent = nullptr);

    /** @brief 析构函数，网络管理器随 parent 自动释放 */
    ~ImageCarPersonDetectService() override;

    /** @return 当前是否处于 busy 检测中状态 */
    bool busy() const;
    /** @return 当前 errorMessage 属性值 */
    QString errorMessage() const;
    /** @return 当前 resultImageUrl 属性值 */
    QString resultImageUrl() const;
    /** @return 当前 detectionCount 属性值 */
    int detectionCount() const;
    /** @return 当前 statusMessage 属性值 */
    QString statusMessage() const;

    /**
     * @brief 发起一次图片目标检测（QML 通过 Q_INVOKABLE 直接调用）
     *
     * @param sourceImageUrl 用户上传的源图片 URL（FileDialog.selectedFile，一般为 file:/// 路径）
     * @param modelType      YOLO 模型类型，如 yolov8n / yolov8s / yolo11n / yolo11s
     * @param targetLabel    界面 ComboBox 中文标签，如「行人」「汽车」「全部」
     *
     * @note 无返回值；结果通过属性变更和 detectFinished 信号通知 QML。
     *       若当前 busy 或参数校验失败，会设置 errorMessage 并 emit detectFinished(false)。
     */
    Q_INVOKABLE void detect(const QUrl &sourceImageUrl,
                            const QString &modelType,
                            const QString &targetLabel);

signals:
    void busyChanged();            ///< busy 属性变化时发出
    void errorMessageChanged();    ///< errorMessage 属性变化时发出
    void resultImageUrlChanged();  ///< resultImageUrl 属性变化时发出
    void detectionCountChanged();  ///< detectionCount 属性变化时发出
    void statusMessageChanged();   ///< statusMessage 属性变化时发出

    /**
     * @brief 一次 detect 流程结束（成功或失败）时发出
     * @param success true 表示后端 code==200 且结果图存在；false 表示任意环节失败
     */
    void detectFinished(bool success);

private:
    /**
     * @brief 解析 backend 目录绝对路径
     * @return backend 根目录（含 main.py），从可执行文件向上查找，找不到则用相对路径兜底
     */
    QString resolveBackendRoot() const;

    /**
     * @brief 将 QML 中文检测目标映射为后端 class_name
     * @param targetLabel 界面显示的中文标签
     * @return YOLO/COCO 类别名（如 person、car、all）；无法映射时返回空字符串
     */
    QString mapTargetToClassName(const QString &targetLabel) const;

    /** @brief 设置 busy 并在值变化时 emit busyChanged */
    void setBusy(bool busy);
    /** @brief 设置 errorMessage 并在值变化时 emit errorMessageChanged */
    void setErrorMessage(const QString &message);
    /** @brief 设置 resultImageUrl 并在值变化时 emit resultImageUrlChanged */
    void setResultImageUrl(const QString &url);
    /** @brief 设置 detectionCount 并在值变化时 emit detectionCountChanged */
    void setDetectionCount(int count);
    /** @brief 设置 statusMessage 并在值变化时 emit statusMessageChanged */
    void setStatusMessage(const QString &message);

    /**
     * @brief 处理 /yoloDetected 异步响应
     * @param reply QNetworkAccessManager::post 返回的 reply，调用方负责 deleteLater
     *
     * 解析 JSON：code、msg、data.url、data.numbers 等；
     * 成功时将相对路径转为本地 file:// URL 写入 resultImageUrl。
     */
    void handleNetworkReply(QNetworkReply *reply);

    QNetworkAccessManager *m_networkManager = nullptr; ///< HTTP 客户端，构造时创建
    bool m_busy = false;                                 ///< 是否正在等待后端响应
    QString m_errorMessage;                              ///< 错误提示文本
    QString m_resultImageUrl;                            ///< 检测结果图 file:// URL
    int m_detectionCount = 0;                            ///< 检测到的目标数量
    QString m_statusMessage;                             ///< 状态/成功摘要文本
    QString m_lastTargetLabel;                           ///< 本次检测的中文目标名，用于成功提示
};

#endif // IMAGECARPERSONDETECTSERVICE_H
