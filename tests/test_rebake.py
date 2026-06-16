"""Headless tests for the additive / incremental re-bake (no window).

Covers the face-subset rasterizer and bake.rebake_faces: re-baking unchanged geometry is
idempotent, and re-baking a face subset only rewrites that subset's texels, compositing
over the previous map everywhere else. See feature-gap C (additive re-bake).
"""

from __future__ import annotations

import numpy as np

from cagebakecake import bake


def _low_quad():
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    return points, tris, normals, uv[tris]


def _high_quad(normal=(0.0, 0.0, 1.0), z=0.5):
    points = np.array([[-0.1, -0.1, z], [1.1, -0.1, z], [1.1, 1.1, z], [-0.1, 1.1, z]],
                      dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile(np.asarray(normal, dtype=np.float64), (4, 1))
    return points, tris, normals


def _cage(low_points, offset=1.0):
    return low_points + np.array([0.0, 0.0, offset])


def test_rasterize_faces_subset_limits_coverage_and_keeps_global_ids():
    _, _, _, luv = _low_quad()
    all_yx, _, _ = bake._rasterize_uv_triangles(luv, 32, 32)
    sub_yx, sub_ti, _ = bake._rasterize_uv_triangles(luv, 32, 32, faces=[1])
    assert 0 < len(sub_yx) < len(all_yx)
    assert set(np.unique(sub_ti).tolist()) == {1}  # tri_index is the global face id


def test_rebake_unchanged_geometry_is_idempotent():
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad()
    cage = _cage(lp)
    base = bake.bake(lp, lt, ln, luv, cage, hp, ht, hn, resolution=32)
    out = bake.rebake_faces(base, lp, lt, ln, luv, cage, hp, ht, hn,
                            faces=[0, 1], resolution=32)
    np.testing.assert_array_equal(out, base)


def test_rebake_only_rewrites_the_given_faces():
    lp, lt, ln, luv = _low_quad()
    cage = _cage(lp)
    base = bake.bake(lp, lt, ln, luv, cage, *_high_quad(), resolution=64)

    # A tilted high poly bakes a different normal; re-bake only face 0.
    tilt = np.array([1.0, 0.0, 1.0]) / np.sqrt(2.0)
    hp2, ht2, hn2 = _high_quad(normal=tilt)
    out = bake.rebake_faces(base, lp, lt, ln, luv, cage, hp2, ht2, hn2,
                            faces=[0], resolution=64)

    yx, _, _ = bake._rasterize_uv_triangles(luv, 64, 64, faces=[0])
    touched = np.zeros((64, 64), dtype=bool)
    touched[yx[:, 0], yx[:, 1]] = True
    # Outside face 0: identical to the previous bake (true composite, not a full re-bake).
    np.testing.assert_array_equal(out[~touched], base[~touched])
    # Inside face 0: the tilt changed the encoded normal.
    assert not np.array_equal(out[touched], base[touched])


def test_rebake_resets_a_newly_missing_region_to_flat():
    lp, lt, ln, luv = _low_quad()
    cage = _cage(lp)
    base = bake.bake(lp, lt, ln, luv, cage, *_high_quad(), resolution=48)
    assert not np.all(base == bake.FLAT_RGB)  # the full bake hit the high poly

    # Re-bake against a high poly moved out of every ray's reach: those texels go flat.
    far = _high_quad(z=50.0)
    out = bake.rebake_faces(base, lp, lt, ln, luv, cage, *far, faces=[0, 1], resolution=48)
    yx, _, _ = bake._rasterize_uv_triangles(luv, 48, 48)
    touched = np.zeros((48, 48), dtype=bool)
    touched[yx[:, 0], yx[:, 1]] = True
    assert np.all(out[touched] == bake.FLAT_RGB)
