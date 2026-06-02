#ifndef STREAMFRAMEIMAGEPROVIDER_H
#define STREAMFRAMEIMAGEPROVIDER_H

#include <QMutex>
#include <QQuickImageProvider>

/** 实时检测帧内存图像提供器，避免逐帧从磁盘加载 JPEG */
class StreamFrameImageProvider : public QQuickImageProvider
{
public:
    static constexpr auto kProviderId = "streamframe";

    StreamFrameImageProvider();

    QImage requestImage(const QString &id, QSize *size, const QSize &requestedSize) override;
    void setFrame(int frameIndex, const QImage &image);

private:
    QMutex m_mutex;
    QImage m_image;
    int m_frameIndex = -1;
};

#endif // STREAMFRAMEIMAGEPROVIDER_H
