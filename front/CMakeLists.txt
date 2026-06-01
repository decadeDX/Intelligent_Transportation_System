cmake_minimum_required(VERSION 3.16)

project(front VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 REQUIRED COMPONENTS Quick QuickControls2 Network)

qt_standard_project_setup(REQUIRES 6.10)

qt_add_executable(appfront
    main.cpp
)

set_source_files_properties(qml/AppTheme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)

qt_add_qml_module(appfront
    URI front
    QML_FILES
        Main.qml
        qml/AppTheme.qml
        qml/ImageCarPersonDected.qml
        qml/VideoCarPersonDected.qml
        qml/ImagePlateDected.qml
        qml/VideoPlateDected.qml
        qml/CarSpeedDected.qml
        qml/LaneDected.qml
        qml/ParkingSpaceDected.qml
        qml/TrafficFlowDected.qml
        qml/TrafficSignDected.qml
        qml/DriverLicenseDected.qml
    SOURCES
        service/ImageCarPersonDetectService.h service/ImageCarPersonDetectService.cpp
        SOURCES service/VideoCarpersonDetectService.h service/VideoCarpersonDetectService.cpp

)

# Qt for iOS sets MACOSX_BUNDLE_GUI_IDENTIFIER automatically since Qt 6.1.
# If you are developing for iOS or macOS you should consider setting an
# explicit, fixed bundle identifier manually though.
set_target_properties(appfront PROPERTIES
#    MACOSX_BUNDLE_GUI_IDENTIFIER com.example.appfront
    MACOSX_BUNDLE_BUNDLE_VERSION ${PROJECT_VERSION}
    MACOSX_BUNDLE_SHORT_VERSION_STRING ${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}
    MACOSX_BUNDLE TRUE
    WIN32_EXECUTABLE TRUE
)

target_link_libraries(appfront
    PRIVATE Qt6::Quick
    PRIVATE Qt6::QuickControls2
    PRIVATE Qt6::Network
)

target_include_directories(appfront PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/service

)


install(TARGETS appfront
    BUNDLE DESTINATION .
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
