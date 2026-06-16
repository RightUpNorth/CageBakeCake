"""Headless tests for the exploded bake (per-part separation).

Covers the pure per-part translation and that baking a separated scene still produces a
valid map - so an exploded bake stops neighbours cross-projecting without distorting the
result. See feature-gap C (exploded bake).
"""

from __future__ import annotations

import numpy as np

from cagebakecake import bake


def test_explode_translation_pushes_parts_radially():
    # Two parts on the x axis, scene centre at the origin.
    pts = np.array([[-2, 0, 0], [-1, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float)
    ranges = [("a", 0, 2), ("b", 2, 2)]
    off = bake.explode_translation(pts, ranges, center=[0, 0, 0], factor=1.0)
    # Part a centroid is x=-1.5, part b x=+1.5; the offset is centroid*factor.
    np.testing.assert_allclose(off[0], [-1.5, 0, 0])
    np.testing.assert_allclose(off[1], [-1.5, 0, 0])
    np.testing.assert_allclose(off[2], [1.5, 0, 0])
    np.testing.assert_allclose(off[3], [1.5, 0, 0])


def test_explode_zero_factor_is_no_op():
    pts = np.array([[-2, 0, 0], [2, 0, 0]], dtype=float)
    off = bake.explode_translation(pts, [("a", 0, 1), ("b", 1, 1)], [0, 0, 0], 0.0)
    assert not off.any()


def _low_quad():
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    return points, tris, normals, uv[tris]


def _high_quad(z=0.5):
    points = np.array([[-0.1, -0.1, z], [1.1, -0.1, z], [1.1, 1.1, z], [-0.1, 1.1, z]],
                      dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    return points, tris, normals


def test_bake_on_translated_geometry_matches_in_place():
    """Translating the low+cage+high together by the same offset (what an exploded bake
    does to a single matched part) leaves the encoded map unchanged - the encode is in
    the tangent frame, which is translation-invariant."""
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad()
    cage = lp + np.array([0.0, 0.0, 1.0])
    base = bake.bake(lp, lt, ln, luv, cage, hp, ht, hn, resolution=32)

    shift = np.array([5.0, -3.0, 2.0])
    shifted = bake.bake(lp + shift, lt, ln, luv, cage + shift, hp + shift, ht, hn,
                        resolution=32)
    np.testing.assert_array_equal(base, shifted)
