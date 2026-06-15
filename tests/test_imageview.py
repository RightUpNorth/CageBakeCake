"""Bitmap-viewer tests (headless, offscreen Qt). Pins the numpy -> QPixmap conversion
that feeds the bake preview, and that the view accepts/clears images without a display."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # must precede any QApplication

import numpy as np
import pytest

pytest.importorskip("qtpy")
from qtpy.QtWidgets import QApplication

from cagebakecake import imageview


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_numpy_to_qpixmap_dimensions(qapp):
    pm = imageview.numpy_to_qpixmap(np.zeros((64, 128, 3), dtype=np.uint8))
    assert (pm.width(), pm.height()) == (128, 64)


def test_numpy_to_qpixmap_drops_alpha(qapp):
    pm = imageview.numpy_to_qpixmap(np.zeros((8, 8, 4), dtype=np.uint8))
    assert (pm.width(), pm.height()) == (8, 8)


def test_image_view_set_and_clear(qapp):
    view = imageview.ImageView()
    view.set_image(np.zeros((10, 12, 3), dtype=np.uint8))
    view.clear()  # no exception, and ready to re-fit the next image
    assert view._needs_fit is True
