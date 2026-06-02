#include "StreamFrameImageProvider.h"

StreamFrameImageProvider::StreamFrameImageProvider()
    : QQuickImageProvider(QQuickImageProvider::Image)
{
}

QImage StreamFrameImageProvider::requestImage(const QString &id,
                                              QSize *size,
                                              const QSize &requestedSize)
{
    Q_UNUSED(id)
    Q_UNUSED(requestedSize)

    QMutexLocker lock(&m_mutex);
    if (size)
        *size = m_image.size();
    return m_image;
}

void StreamFrameImageProvider::setFrame(int frameIndex, const QImage &image)
{
    QMutexLocker lock(&m_mutex);
    m_frameIndex = frameIndex;
    m_image = image;
}
