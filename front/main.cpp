#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>

#include "service/CarSpeedDetectService.h"
#include "service/LaneDetectService.h"
#include "service/ParkingSpaceDetectService.h"
#include "service/StreamFrameImageProvider.h"
#include "service/TrafficFlowDetectService.h"
#include "service/TrafficSignDetectService.h"
#include "service/VideoCarpersonDetectService.h"
#include "service/VideoPlateDetectService.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QQuickStyle::setStyle("Fusion");
    QQmlApplicationEngine engine;
    auto *streamFrameProvider = new StreamFrameImageProvider;
    engine.addImageProvider(QLatin1String(StreamFrameImageProvider::kProviderId),
                            streamFrameProvider);
    CarSpeedDetectService::setFrameImageProvider(streamFrameProvider);
    LaneDetectService::setFrameImageProvider(streamFrameProvider);
    ParkingSpaceDetectService::setFrameImageProvider(streamFrameProvider);
    TrafficFlowDetectService::setFrameImageProvider(streamFrameProvider);
    TrafficSignDetectService::setFrameImageProvider(streamFrameProvider);
    VideoCarPersonDetectService::setFrameImageProvider(streamFrameProvider);
    VideoPlateDetectService::setFrameImageProvider(streamFrameProvider);

    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &app,
        []() { QCoreApplication::exit(-1); },
        Qt::QueuedConnection);
    engine.loadFromModule("front", "Main");

    return QCoreApplication::exec();
}
