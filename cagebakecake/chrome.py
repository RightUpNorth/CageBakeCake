"""Frameless-window chrome: a draggable title bar and edge resize grips.

Going frameless (Qt.FramelessWindowHint) drops the native title bar so the design's
single 48px themed bar can be the real one - but it also drops native window move and
resize. This module restores both with plain Qt (no per-platform native hit-testing):

- ``DragBar`` is a strip that moves its top-level window on drag and toggles
  maximize on double-click. The title bar is built on top of it.
- ``install_resize_grips`` lays eight thin grip widgets around the window border
  that resize it. They sit *above* the content (including the VTK viewport, which
  would otherwise eat edge mouse events), so resize works on every edge.

Global cursor positions come from ``QCursor.pos()`` so the same code works
regardless of the Qt mouse-event API version.
"""

from __future__ import annotations

from qtpy.QtCore import QObject, QPoint, QRect, QRectF, Qt
from qtpy.QtGui import QBrush, QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from qtpy.QtWidgets import QWidget

_GRIP = 6  # px hit zone for the edge/corner resize grips


def cake_icon(size: int, color: str) -> QPixmap:
    """A small cupcake glyph (the app mark) painted in ``color`` on transparency, so it
    reads as a logo over the accent-filled app-mark square. Drawn rather than shipped
    as an asset to keep the mark recoloring with the theme."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    s = size
    # Cup (trapezoid): wider at the frosting line, tapering to the base.
    cup = QPainterPath()
    cup.moveTo(0.27 * s, 0.55 * s)
    cup.lineTo(0.73 * s, 0.55 * s)
    cup.lineTo(0.66 * s, 0.84 * s)
    cup.lineTo(0.34 * s, 0.84 * s)
    cup.closeSubpath()
    p.drawPath(cup)
    # Frosting dome.
    p.drawEllipse(QRectF(0.22 * s, 0.34 * s, 0.56 * s, 0.34 * s))
    p.drawEllipse(QRectF(0.16 * s, 0.42 * s, 0.30 * s, 0.26 * s))
    p.drawEllipse(QRectF(0.54 * s, 0.42 * s, 0.30 * s, 0.26 * s))
    # Candle + flame.
    pen = QPen(c)
    pen.setWidthF(max(1.0, 0.06 * s))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(int(0.5 * s), int(0.30 * s), int(0.5 * s), int(0.14 * s))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(0.44 * s, 0.04 * s, 0.12 * s, 0.12 * s))
    p.end()
    return pm


class DragBar(QWidget):
    """A title-bar strip that moves (and maximizes on double-click) its window."""

    def __init__(self, window: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self._window = window
        self._offset: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self._window.isMaximized():
            # Remember where in the window the grab started, so the window tracks the
            # cursor without jumping.
            self._offset = QCursor.pos() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            self._window.move(QCursor.pos() - self._offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        super().mouseDoubleClickEvent(event)


class _Grip(QWidget):
    """One edge/corner resize handle, parented to (and resizing) the window."""

    def __init__(self, window: QWidget, left: bool, top: bool, right: bool,
                 bottom: bool, cursor: Qt.CursorShape):
        super().__init__(window)
        self._window = window
        self._edges = (left, top, right, bottom)
        self.setCursor(cursor)
        self._start = QPoint()
        self._geo = QRect()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self._window.isMaximized():
            self._start = QCursor.pos()
            self._geo = self._window.geometry()

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton) or self._window.isMaximized():
            return
        delta = QCursor.pos() - self._start
        left, top, right, bottom = self._edges
        g = QRect(self._geo)
        if left:
            g.setLeft(g.left() + delta.x())
        if right:
            g.setRight(g.right() + delta.x())
        if top:
            g.setTop(g.top() + delta.y())
        if bottom:
            g.setBottom(g.bottom() + delta.y())
        mn = self._window.minimumSize()
        if g.width() >= mn.width() and g.height() >= mn.height():
            self._window.setGeometry(g)


class _GripLayout(QObject):
    """Keeps the eight grips pinned to the window border as it resizes."""

    def __init__(self, window: QWidget, grips: list[tuple[_Grip, str]]):
        super().__init__(window)
        self._window = window
        self._grips = grips
        window.installEventFilter(self)
        self._reposition()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window and event.type() in (event.Type.Resize, event.Type.Show):
            self._reposition()
        return False

    def _reposition(self) -> None:
        w = self._window.width()
        h = self._window.height()
        g = _GRIP
        # placement keyed by the grip's role string
        rects = {
            "left": QRect(0, g, g, h - 2 * g),
            "right": QRect(w - g, g, g, h - 2 * g),
            "top": QRect(g, 0, w - 2 * g, g),
            "bottom": QRect(g, h - g, w - 2 * g, g),
            "tl": QRect(0, 0, g, g),
            "tr": QRect(w - g, 0, g, g),
            "bl": QRect(0, h - g, g, g),
            "br": QRect(w - g, h - g, g, g),
        }
        for grip, role in self._grips:
            grip.setGeometry(rects[role])
            grip.raise_()


def install_resize_grips(window: QWidget) -> None:
    """Add eight resize grips (4 edges + 4 corners) around the frameless window."""
    specs = [
        ("left", True, False, False, False, Qt.SizeHorCursor),
        ("right", False, False, True, False, Qt.SizeHorCursor),
        ("top", False, True, False, False, Qt.SizeVerCursor),
        ("bottom", False, False, False, True, Qt.SizeVerCursor),
        ("tl", True, True, False, False, Qt.SizeFDiagCursor),
        ("br", False, False, True, True, Qt.SizeFDiagCursor),
        ("tr", False, True, True, False, Qt.SizeBDiagCursor),
        ("bl", True, False, False, True, Qt.SizeBDiagCursor),
    ]
    grips: list[tuple[_Grip, str]] = []
    for role, left, top, right, bottom, cursor in specs:
        grip = _Grip(window, left, top, right, bottom, cursor)
        grips.append((grip, role))
    window._resize_grips = _GripLayout(window, grips)  # keep a ref alive on the window
