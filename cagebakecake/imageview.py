"""A zoom/pan 2D image viewer for inspecting baked maps in-app.

Pure Qt, fed numpy RGB (H,W,3) uint8 arrays - the same buffers the bakes already
produce (normal / AO / curvature). It exists because, until now, the bakes either only
wrote a PNG (AO, curvature) or only previewed as lighting on the 3D low poly (normal):
there was no way to see the actual texture. Kept apart from the 3D viewport (window.py)
so it has no dependency on PyVista/VTK.
"""

from __future__ import annotations

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtGui import QImage, QPainter, QPixmap
from qtpy.QtWidgets import QGraphicsScene, QGraphicsView


def numpy_to_qpixmap(image: np.ndarray) -> QPixmap:
    """An RGB (H,W,3) uint8 array -> QPixmap. The QImage is copied so the pixmap owns
    its pixels and does not alias the (possibly temporary) numpy buffer."""
    img = np.ascontiguousarray(np.asarray(image)[..., :3].astype(np.uint8))
    h, w = img.shape[:2]
    qimg = QImage(img.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class ImageView(QGraphicsView):
    """A pannable, wheel-zoomable single-image view. Drag to pan, wheel to zoom; the
    first image shown is fitted to the widget."""

    _ZOOM_STEP = 1.25

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = self._scene.addPixmap(QPixmap())
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(Qt.darkGray)
        self._needs_fit = True

    def set_image(self, image: np.ndarray) -> None:
        self._item.setPixmap(numpy_to_qpixmap(image))
        self._scene.setSceneRect(self._item.boundingRect())
        if self._needs_fit:
            self.fit()
            self._needs_fit = False

    def clear(self) -> None:
        self._item.setPixmap(QPixmap())
        self._needs_fit = True

    def fit(self) -> None:
        if not self._item.pixmap().isNull():
            self.resetTransform()
            self.fitInView(self._item, Qt.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        if self._item.pixmap().isNull():
            return
        up = event.angleDelta().y() > 0
        factor = self._ZOOM_STEP if up else 1.0 / self._ZOOM_STEP
        self.scale(factor, factor)
