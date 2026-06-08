/**
 * @file GradioWebLauncher.cpp
 */

#include "GradioWebLauncher.h"

#include <QCoreApplication>
#include <QDesktopServices>
#include <QDir>
#include <QFileInfo>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QProcess>
#include <QProcessEnvironment>
#include <QTimer>
#include <QUrl>

#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

namespace {
constexpr auto kInferenceBaseUrl = "http://127.0.0.1:8000";
constexpr auto kInferenceHealthPath = "/docs";
constexpr auto kGradioBaseUrl = "http://127.0.0.1:7869";
constexpr int kPollIntervalMs = 500;
constexpr int kStartupTimeoutMs = 120000;
}

GradioWebLauncher::GradioWebLauncher(QObject *parent)
    : QObject(parent)
    , m_networkManager(new QNetworkAccessManager(this))
    , m_pollTimer(new QTimer(this))
{
    m_pollTimer->setInterval(kPollIntervalMs);
    connect(m_pollTimer, &QTimer::timeout, this, &GradioWebLauncher::pollGradioHealth);
}

GradioWebLauncher::~GradioWebLauncher()
{
    stopPolling();
    stopOwnedProcess();
}

bool GradioWebLauncher::busy() const
{
    return m_busy;
}

void GradioWebLauncher::setBusy(bool busy)
{
    if (m_busy == busy)
        return;
    m_busy = busy;
    emit busyChanged();
}

QString GradioWebLauncher::resolveBackendRoot() const
{
    QDir dir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 6; ++i) {
        const QString candidate = dir.filePath(QStringLiteral("backend"));
        if (QFileInfo::exists(candidate + QStringLiteral("/app.py")))
            return QDir(candidate).absolutePath();

        if (!dir.cdUp())
            break;
    }

    return QDir(QCoreApplication::applicationDirPath())
        .filePath(QStringLiteral("../../../backend"));
}

QString GradioWebLauncher::resolvePythonExecutable(const QString &backendRoot) const
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

void GradioWebLauncher::mergeNoProxyEnv(QProcessEnvironment &env) const
{
    const QStringList bypass = {
        QStringLiteral("localhost"),
        QStringLiteral("127.0.0.1"),
        QStringLiteral("::1"),
        QStringLiteral("0.0.0.0"),
        QStringLiteral("<local>"),
    };

    auto mergeList = [&bypass](const QString &current) {
        QStringList parts;
        for (const QString &p : current.split(QLatin1Char(','))) {
            const QString t = p.trimmed();
            if (!t.isEmpty())
                parts.append(t);
        }
        for (const QString &host : bypass) {
            if (!parts.contains(host))
                parts.append(host);
        }
        return parts.join(QLatin1Char(','));
    };

    env.insert(QStringLiteral("NO_PROXY"), mergeList(env.value(QStringLiteral("NO_PROXY"))));
    env.insert(QStringLiteral("no_proxy"), mergeList(env.value(QStringLiteral("no_proxy"))));
}

void GradioWebLauncher::probeUrl(const QString &url,
                                 std::function<void(bool reachable)> callback)
{
    const QUrl endpoint(url);
    QNetworkRequest netRequest(endpoint);
    netRequest.setTransferTimeout(2000);

    QNetworkReply *reply = m_networkManager->get(netRequest);
    connect(reply, &QNetworkReply::finished, this, [reply, callback]() {
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const bool reachable = reply->error() == QNetworkReply::NoError && status >= 200 && status < 500;
        reply->deleteLater();
        callback(reachable);
    });
}

void GradioWebLauncher::probeInferenceServer(std::function<void(bool reachable)> callback)
{
    probeUrl(QStringLiteral("%1%2").arg(kInferenceBaseUrl, kInferenceHealthPath), callback);
}

void GradioWebLauncher::stopPolling()
{
    if (m_pollTimer->isActive())
        m_pollTimer->stop();
}

void GradioWebLauncher::stopOwnedProcess()
{
    if (!m_startedByUs || !m_process)
        return;

    m_process->disconnect(this);
    if (m_process->state() != QProcess::NotRunning) {
        m_process->terminate();
        if (!m_process->waitForFinished(3000))
            m_process->kill();
        m_process->waitForFinished(2000);
    }

    m_process->deleteLater();
    m_process = nullptr;
    m_startedByUs = false;
}

void GradioWebLauncher::openBrowser()
{
    const bool opened = QDesktopServices::openUrl(QUrl(QStringLiteral("%1/").arg(kGradioBaseUrl)));
    if (!opened) {
        markLaunchFailure(tr("无法调用系统默认浏览器，请手动访问：%1").arg(kGradioBaseUrl));
        return;
    }
    markLaunchSuccess();
}

void GradioWebLauncher::markLaunchSuccess()
{
    if (m_launchFinished)
        return;

    m_launchFinished = true;
    stopPolling();
    setBusy(false);
    emit webUiOpened();
}

void GradioWebLauncher::markLaunchFailure(const QString &message)
{
    if (m_launchFinished)
        return;

    m_launchFinished = true;
    stopPolling();
    stopOwnedProcess();
    setBusy(false);
    emit launchFailed(message);
}

void GradioWebLauncher::beginLaunchGradio()
{
    probeUrl(QStringLiteral("%1/").arg(kGradioBaseUrl), [this](bool gradioUp) {
        if (gradioUp) {
            openBrowser();
            return;
        }

        const QString backendRoot = resolveBackendRoot();
        const QString pythonExe = resolvePythonExecutable(backendRoot);

        if (!QFileInfo::exists(backendRoot + QStringLiteral("/app.py"))) {
            markLaunchFailure(tr("未找到 backend/app.py"));
            return;
        }
        if (pythonExe.isEmpty()) {
            markLaunchFailure(tr("未找到 backend/.venv 中的 Python，请先配置虚拟环境"));
            return;
        }

        launchGradioProcess(backendRoot, pythonExe);
        m_pollTimer->start();
    });
}

void GradioWebLauncher::launchGradioProcess(const QString &backendRoot,
                                            const QString &pythonExe)
{
    if (m_process) {
        m_process->deleteLater();
        m_process = nullptr;
    }

    m_process = new QProcess(this);
    m_process->setWorkingDirectory(backendRoot);
    m_process->setProgram(pythonExe);
    m_process->setArguments({QStringLiteral("app.py")});

    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    mergeNoProxyEnv(env);
    m_process->setProcessEnvironment(env);

#ifdef Q_OS_WIN
    m_process->setCreateProcessArgumentsModifier(
        [](QProcess::CreateProcessArguments *args) {
            args->flags |= CREATE_NO_WINDOW;
        });
#endif

    connect(m_process, &QProcess::finished, this,
            [this](int exitCode, QProcess::ExitStatus exitStatus) {
                Q_UNUSED(exitStatus);
                if (m_launchFinished)
                    return;
                markLaunchFailure(
                    tr("Gradio 进程已退出 (code=%1)，请检查 backend 依赖与端口 7869 是否被占用")
                        .arg(exitCode));
            });
    connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (m_launchFinished)
            return;
        if (error == QProcess::FailedToStart)
            markLaunchFailure(tr("无法启动 app.py，请确认 Python 虚拟环境可用"));
    });

    m_process->start();
    m_startedByUs = true;
}

void GradioWebLauncher::pollGradioHealth()
{
    m_startupElapsedMs += kPollIntervalMs;
    if (m_startupElapsedMs >= kStartupTimeoutMs) {
        markLaunchFailure(tr("Gradio Web 启动超时，请稍后重试或手动运行：python app.py"));
        return;
    }

    probeUrl(QStringLiteral("%1/").arg(kGradioBaseUrl), [this](bool reachable) {
        if (reachable)
            openBrowser();
    });
}

void GradioWebLauncher::startWebUi()
{
    if (m_busy)
        return;

    setBusy(true);
    m_launchFinished = false;
    m_startupElapsedMs = 0;
    stopPolling();

    probeInferenceServer([this](bool inferenceReady) {
        if (!inferenceReady) {
            setBusy(false);
            emit inferenceServerRequired();
            return;
        }
        beginLaunchGradio();
    });
}
