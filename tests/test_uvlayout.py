"""Headless tests for the UV layout renderer (no window).

layout_image draws the low poly's UV island edges over a checkerboard, or over a baked
map (a UV-space texture view). See feature-gap D (UV layout view).
"""

from __future__ import annotations

import numpy as np

from cagebakecake import uvlayout


def _uvs():
    """A single UV triangle well inside the 0-1 square (per-corner (1,3,2))."""
    return np.array([[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]], dtype=np.float64)


def test_layout_over_checker_has_edges_and_background():
    img = uvlayout.layout_image(_uvs(), 64, 64)
    assert img.shape == (64, 64, 3)
    assert np.any(np.all(img == uvlayout.EDGE, axis=-1))      # island wireframe drawn
    assert np.any(np.all(img == uvlayout.CHECK_A, axis=-1))   # both checker shades show
    assert np.any(np.all(img == uvlayout.CHECK_B, axis=-1))


def test_layout_over_base_only_changes_edge_pixels():
    base = np.full((64, 64, 3), 100, dtype=np.uint8)
    img = uvlayout.layout_image(_uvs(), base=base)
    assert img.shape == base.shape   # takes the base's resolution
    edge = np.all(img == uvlayout.EDGE, axis=-1)
    assert edge.any()
    np.testing.assert_array_equal(img[~edge], base[~edge])  # texture untouched off seams


def test_empty_uvs_returns_background_only():
    img = uvlayout.layout_image(np.empty((0, 3, 2)), 32, 32)
    assert img.shape == (32, 32, 3)
    assert not np.any(np.all(img == uvlayout.EDGE, axis=-1))


def test_line_points_are_gap_free():
    xs, ys = uvlayout._line_points(
        np.array([0.0]), np.array([0.0]), np.array([10.0]), np.array([0.0]))
    assert sorted(xs.tolist()) == list(range(11))
    assert np.all(ys == 0)
