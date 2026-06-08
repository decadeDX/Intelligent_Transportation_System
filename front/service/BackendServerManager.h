#ifndef BACKENDSERVERMANAGER_H
#define BACKENDSERVERMANAGER_H

#include <QObject>
#include <QProcess>
#include <functional>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QTimer;

class BackendServerManager : public QObject
{  
    Q_OBJECT
    QML_ELEMENT

    /** @brief 状态栏显示文本 */
    Q_PROPERTY(QString statusText READ statusText NOTIFY statusTextChanged)
    /** @brief 推理服务器是否已成功就绪 */
    Q_PROPERTY(bool serverReady READ serverReady NOTIFY serverReadyChanged)
    /** @brief 推理服务器是否启动失败 */
    Q_PROPERTY(bool serverFailed READ serverFailed NOTIFY serverFailedChanged)
    Q_PROPERTY(bool serverBusy READ serverBusy NOTIFY serverBusyChanged)


public:
    explicit BackendServerManager(QObject *parent = nullptr);
    ~BackendServerManager() override;

    QString statusText() const;
    bool serverReady() const;
    bool serverFailed() const;
    bool serverBusy() const;

    /** @brief 启动后端推理服务器（若已在运行则直接标记成功） */
    Q_INVOKABLE void startServer();
    Q_INVOKABLE void restartServer();
    /** @brief 清空 backend/upload/source 与 backend/upload/detected 下的文件 */
    Q_INVOKABLE bool clearTemporaryFiles();

signals:
    void statusTextChanged();
    void serverReadyChanged();
    void serverFailedChanged();
    void serverBusyChanged();
    /** @brief 启动流程结束，success 为 true 表示服务可用 */
    void serverStartupFinished(bool success);

private slots:
    void pollServerHealth();
    void onProcessFinished(int exitCode, QProcess::ExitStatus exitStatus);
    void onProcessError(QProcess::ProcessError error);

private:
    QString resolveBackendRoot() const;
    QString resolvePythonExecutable(const QString &backendRoot) const;
    void probeServer(std::function<void(bool reachable)> callback);
    void launchBackendProcess(const QString &backendRoot, const QString &pythonExe);
    void setStatusText(const QString &text);
    void setServerReady(bool ready);
    void setServerFailed(bool failed);
    void setServerBusy(bool busy);
    void markSuccess();
    void markFailure();
    void stopPolling();
    void stopOwnedProcess();

    QProcess *m_process = nullptr;
    QNetworkAccessManager *m_networkManager = nullptr;
    QTimer *m_pollTimer = nullptr;

    QString m_statusText;
    bool m_serverReady = false;
    bool m_serverFailed = false;
    bool m_serverBusy = false;
    bool m_startedByUs = false;
    bool m_startupFinished = false;
    qint64 m_startupElapsedMs = 0;
};

#endif // BACKENDSERVERMANAGER_H
