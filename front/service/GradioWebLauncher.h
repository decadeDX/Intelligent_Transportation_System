/**
 * @file GradioWebLauncher.h
 * @brief 启动 backend/app.py（Gradio Web）并用系统默认浏览器打开
 */

#ifndef GRADIOWEBLAUNCHER_H
#define GRADIOWEBLAUNCHER_H

#include <QObject>
#include <QProcess>
#include <functional>
#include <qqmlintegration.h>

class QNetworkAccessManager;
class QTimer;

class GradioWebLauncher : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)

public:
    explicit GradioWebLauncher(QObject *parent = nullptr);
    ~GradioWebLauncher() override;

    bool busy() const;

    /** 需推理服务(8000)已就绪；启动或复用 Gradio(7869) 并打开浏览器 */
    Q_INVOKABLE void startWebUi();

signals:
    void busyChanged();
    /** 推理服务器未启动 */
    void inferenceServerRequired();
    /** Gradio 启动或打开浏览器失败 */
    void launchFailed(const QString &message);
    /** 已在浏览器中打开 Web 地址 */
    void webUiOpened();

private slots:
    void pollGradioHealth();

private:
    QString resolveBackendRoot() const;
    QString resolvePythonExecutable(const QString &backendRoot) const;
    void mergeNoProxyEnv(QProcessEnvironment &env) const;
    void probeUrl(const QString &url, std::function<void(bool reachable)> callback);
    void probeInferenceServer(std::function<void(bool reachable)> callback);
    void beginLaunchGradio();
    void launchGradioProcess(const QString &backendRoot, const QString &pythonExe);
    void openBrowser();
    void markLaunchSuccess();
    void markLaunchFailure(const QString &message);
    void setBusy(bool busy);
    void stopPolling();
    void stopOwnedProcess();

    QProcess *m_process = nullptr;
    QNetworkAccessManager *m_networkManager = nullptr;
    QTimer *m_pollTimer = nullptr;

    bool m_busy = false;
    bool m_startedByUs = false;
    bool m_launchFinished = false;
    qint64 m_startupElapsedMs = 0;
};

#endif // GRADIOWEBLAUNCHER_H
