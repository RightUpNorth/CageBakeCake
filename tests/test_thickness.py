"""Headless test for the thickness bake (inward distance to the far wall). Feature-gap C."""

from __future__ import annotations

import numpy as np

from cagebakecake import bake, recipe


def _low_quad():
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))      # surface faces +Z; inward is -Z
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    return points, tris, normals, uv[tris]


def _wall(z):
    # A quad spanning past the unit square at height z (the far wall the inward ray hits).
    points = np.array([[-0.1, -0.1, z], [1.1, -0.1, z], [1.1, 1.1, z], [-0.1, 1.1, z]],
                      dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    return points, tris


def test_thickness_measures_inward_distance():
    lp, lt, ln, luv = _low_quad()
    hp, ht = _wall(z=-0.5)   # 0.5 below the surface, along the inward (-Z) ray
    img = bake.bake_thickness(lp, lt, ln, luv, lp, hp, ht, resolution=32, value_range=1.0)
    interior = img[6:26, 6:26].reshape(-1, 3)
    assert np.all(interior[:, 0] == interior[:, 1])             # grayscale
    assert abs(interior[:, 0].mean() - 0.5 * 255) < 8          # thickness 0.5 over range 1.0


def test_thicker_wall_is_brighter():
    lp, lt, ln, luv = _low_quad()
    near = bake.bake_thickness(lp, lt, ln, luv, lp, *_wall(z=-0.3), resolution=16,
                               value_range=1.0)
    far = bake.bake_thickness(lp, lt, ln, luv, lp, *_wall(z=-0.8), resolution=16,
                              value_range=1.0)
    assert far[6:10, 6:10, 0].mean() > near[6:10, 6:10, 0].mean()


def test_thickness_is_a_bakeable_kind():
    assert "thickness" in recipe.BAKEABLE_KINDS
