#ifndef DRIVERLICENSEDETECTSERVICE_H
#define DRIVERLICENSEDETECTSERVICE_H

#include <QObject>
#include <QUrl>
#include <QVariantList>
#include <QVariantMap>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QNetworkReply;

class DriverLicenseDetectService : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorMessage READ errorMessage NOTIFY errorMessageChanged)
    Q_PROPERTY(QString resultImageUrl READ resultImageUrl NOTIFY resultImageUrlChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusMessageChanged)
    Q_PROPERTY(int textNumber READ textNumber NOTIFY textNumberChanged)
    Q_PROPERTY(QVariantMap licenseInfo READ licenseInfo NOTIFY licenseInfoChanged)
    Q_PROPERTY(QVariantList textList READ textList NOTIFY textListChanged)
    Q_PROPERTY(QString fullText READ fullText NOTIFY fullTextChanged)

public:
    explicit DriverLicenseDetectService(QObject *parent = nullptr);
    ~DriverLicenseDetectService() override;

    bool busy() const;
    QString errorMessage() const;
    QString resultImageUrl() const;
    QString statusMessage() const;
    int textNumber() const;
    QVariantMap licenseInfo() const;
    QVariantList textList() const;
    QString fullText() const;

    Q_INVOKABLE void detect(const QUrl &sourceImageUrl, const QString &recognitionType = QStringLiteral("driver_license"));

signals:
    void busyChanged();
    void errorMessageChanged();
    void resultImageUrlChanged();
    void statusMessageChanged();
    void textNumberChanged();
    void licenseInfoChanged();
    void textListChanged();
    void fullTextChanged();
    void detectFinished(bool success);

private:
    QString resolveBackendRoot() const;
    void setBusy(bool value);
    void setErrorMessage(const QString &value);
    void setResultImageUrl(const QString &value);
    void setStatusMessage(const QString &value);
    void setTextNumber(int value);
    void setLicenseInfo(const QVariantMap &value);
    void setTextList(const QVariantList &value);
    void setFullText(const QString &value);
    void resetResultState();
    bool prepareUpload(const QUrl &sourceImageUrl, QString *destPath);
    void handleNetworkReply(QNetworkReply *reply);

    QNetworkAccessManager *m_networkManager = nullptr;
    bool m_busy = false;
    QString m_errorMessage;
    QString m_resultImageUrl;
    QString m_statusMessage;
    int m_textNumber = 0;
    QVariantMap m_licenseInfo;
    QVariantList m_textList;
    QString m_fullText;
};

#endif // DRIVERLICENSEDETECTSERVICE_H
