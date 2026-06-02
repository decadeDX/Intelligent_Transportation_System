#ifndef IMAGEPLATEDETECTSERVICE_H
#define IMAGEPLATEDETECTSERVICE_H

#include <QObject>
#include <QUrl>
#include <QVariantList>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;

/// 图片车牌检测服务：封装 /plateDetected 接口，供 QML 绑定
class ImagePlateDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultImageUrl READ resultImageUrl NOTIFY resultImageUrlChanged)
    Q_PROPERTY(int detectionCount READ detectionCount NOTIFY detectionCountChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(QVariantList plateList READ plateList NOTIFY plateListChanged)

public:
    explicit ImagePlateDetectService(QObject *parent = nullptr);
    ~ImagePlateDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultImageUrl() const;
    int detectionCount() const;
    QString statusMessage() const;
    QVariantList plateList() const;

    /// 发起一次图片车牌检测，只需图片路径
    Q_INVOKABLE void detect(const QUrl &sourceImageUrl);

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultImageUrlChanged();
    void detectionCountChanged();
    void statusMessageChanged();
    void plateListChanged();
    void detectFinished(bool success);

private:
    QString resolveBackendRoot() const;
    void setBusy(bool v);
    void setErrorMessage(const QString &v);
    void setResultImageUrl(const QString &v);
    void setDetectionCount(int v);
    void setStatusMessage(const QString &v);
    void setPlateList(const QVariantList &v);
    void handleNetworkReply(QNetworkReply *reply);

    QNetworkAccessManager *m_networkManager = nullptr;
    bool m_busy = false;
    QString m_errorMessage;
    QString m_resultImageUrl;
    int m_detectionCount = 0;
    QString m_statusMessage;
    QVariantList m_plateList;
};

#endif // IMAGEPLATEDETECTSERVICE_H
