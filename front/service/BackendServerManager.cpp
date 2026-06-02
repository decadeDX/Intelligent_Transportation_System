/**
 * @file BackendServerManager.cpp
 * @brief BackendServerManager 的实现：进程启动与健康检查
 */

#include "BackendServerManager.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <functional>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QProcess>
#include <QTimer>
#include <QUrl>

#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

namespace {
constexpr auto kApiBaseUrl = "http://127.0.0.1:8000";
constexpr auto kHealthCheckPath = "/docs";
constexpr int kPollIntervalMs = 500;
constexpr int kStartupTimeoutMs = 120000;
}

BackendServerManager::BackendServerManager(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
    , m_pollTimer(new QTimer(this))
{
    m_pollTimer->setInterval(kPollIntervalMs);
    connect(m_pollTimer, &QTimer::timeout, this, &BackendServerManager::pollServerHealth);
}

BackendServerManager::~BackendServerManager()
{
    stopPolling();
    stopOwnedProcess();
}

QString BackendServerManager::statusText() const
{
    return m_statusText;
}

bool BackendServerManager::serverReady() const
{
    return m_serverReady;
}

bool BackendServerManager::serverFailed() const
{
    return m_serverFailed;
}

void BackendServerManager::setStatusText(const QString &text)
{
    if (m_statusText == text)
        return;
    m_statusText = text;
    emit statusTextChanged();
}

void BackendServerManager::setServerReady(bool ready)
{
    if (m_serverReady == ready)
        return;
    m_serverReady = ready;
    emit serverReadyChanged();
}

void BackendServerManager::setServerFailed(bool failed)
{
    if (m_serverFailed == failed)
        return;
    m_serverFailed = failed;
    emit serverFailedChanged();
}

QString BackendServerManager::resolveBackendRoot() const
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

QString BackendServerManager::resolvePythonExecutable(const QString &backendRoot) const
{
#ifdef Q_OS_WIN
    const QString venvPython = QDir(backendRoot).filePath(QStringLiteral(".venv/Scripts/python.exe"));
#else
    const QString venvPython = QDir(backendRoot).filePath(QStringLiteral(".venv/bin/python"));
#endif
    if (QFileInfo::exists(venvPython))
        return QDir(venvPython).absolutePath();

    return {};
}

void BackendServerManager::probeServer(std::function<void(bool reachable)> callback)
{
    QNetworkRequest request(QUrl(QStringLiteral("%1%2").arg(kApiBaseUrl, kHealthCheckPath)));
    request.setTransferTimeout(2000);

    QNetworkReply *reply = m_networkManager->get(request);
    connect(reply, &QNetworkReply::finished, this, [reply, callback]() {
        const bool reachable = reply->error() == QNetworkReply::NoError
                               && reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() == 200;
        reply->deleteLater();
        callback(reachable);
    });
}

void BackendServerManager::markSuccess()
{
    if (m_startupFinished)
        return;

    m_startupFinished = true;
    stopPolling();
    setServerFailed(false);
    setServerReady(true);
    setStatusText(tr("推理服务器启动成功!"));
    emit serverStartupFinished(true);
}

void BackendServerManager::markFailure()
{
    if (m_startupFinished)
        return;

    m_startupFinished = true;
    stopPolling();
    setServerReady(false);
    setServerFailed(true);
    setStatusText(tr("推理服务器启动失败!"));
    emit serverStartupFinished(false);
}

void BackendServerManager::stopPolling()
{
    if (m_pollTimer->isActive())
        m_pollTimer->stop();
}

void BackendServerManager::stopOwnedProcess()
{
    if (!m_startedByUs || !m_process)
        return;

    if (m_process->state() != QProcess::NotRunning) {
        m_process->terminate();
        if (!m_process->waitForFinished(3000))
            m_process->kill();
    }
}

void BackendServerManager::startServer()
{
    if (m_startupFinished || m_pollTimer->isActive())
        return;

    setServerReady(false);
    setServerFailed(false);
    setStatusText(tr("正在启动推理服务器..."));
    m_startupElapsedMs = 0;

    probeServer([this](bool reachable) {
        if (reachable) {
            markSuccess();
            return;
        }

        const QString backendRoot = resolveBackendRoot();
        const QString pythonExe = resolvePythonExecutable(backendRoot);

        if (!QFileInfo::exists(backendRoot + QStringLiteral("/main.py"))) {
            markFailure();
            return;
        }

        if (pythonExe.isEmpty()) {
            markFailure();
            return;
        }

        launchBackendProcess(backendRoot, pythonExe);
        m_pollTimer->start();
    });
}

void BackendServerManager::launchBackendProcess(const QString &backendRoot,
                                                const QString &pythonExe)
{
    if (m_process) {
        m_process->deleteLater();
        m_process = nullptr;
    }

    m_process = new QProcess(this);
    m_process->setWorkingDirectory(backendRoot);
    m_process->setProgram(pythonExe);
    m_process->setArguments({QStringLiteral("main.py")});

#ifdef Q_OS_WIN
    m_process->setCreateProcessArgumentsModifier(
        [](QProcess::CreateProcessArguments *args) {
            args->flags |= CREATE_NO_WINDOW;
        });
#endif

    connect(m_process, &QProcess::finished, this, &BackendServerManager::onProcessFinished);
    connect(m_process,
            &QProcess::errorOccurred,
            this,
            &BackendServerManager::onProcessError);

    m_process->start();
    m_startedByUs = true;
}

void BackendServerManager::pollServerHealth()
{
    m_startupElapsedMs += kPollIntervalMs;
    if (m_startupElapsedMs >= kStartupTimeoutMs) {
        markFailure();
        return;
    }

    probeServer([this](bool reachable) {
        if (reachable)
            markSuccess();
    });
}

void BackendServerManager::onProcessFinished(int exitCode, QProcess::ExitStatus exitStatus)
{
    Q_UNUSED(exitCode);
    Q_UNUSED(exitStatus);

    if (!m_startupFinished)
        markFailure();
}

void BackendServerManager::onProcessError(QProcess::ProcessError error)
{
    if (error == QProcess::FailedToStart && !m_startupFinished)
        markFailure();
}
