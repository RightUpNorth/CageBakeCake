"""Cage math tests (headless). Covers the M8.2 skew blend; the drag/projection helpers
are exercised through the app, this pins the pure firing-direction math."""

from __future__ import annotations

import numpy as np

from cagebakecake import cage


def test_blend_normals_endpoints():
    hard = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    soft = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    assert np.allclose(cage.blend_normals(hard, soft, 0.0), hard)  # skew 0 -> hard
    assert np.allclose(cage.blend_normals(hard, soft, 1.0), soft)  # skew 1 -> soft


def test_blend_normals_midpoint_is_normalized_lerp():
    hard = np.array([[1.0, 0.0, 0.0]])
    soft = np.array([[0.0, 0.0, 1.0]])
    out = cage.blend_normals(hard, soft, 0.5)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)
    assert np.allclose(out, [[np.sqrt(0.5), 0.0, np.sqrt(0.5)]])


def test_blend_normals_per_vertex_skew():
    hard = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    soft = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    out = cage.blend_normals(hard, soft, np.array([0.0, 1.0]))
    assert np.allclose(out[0], hard[0])  # vertex 0 fully hard
    assert np.allclose(out[1], soft[1])  # vertex 1 fully soft


def test_resample_cage_hits_along_normal():
    # Low quad in z=0 facing +Z; an arbitrary cage quad at z=2 (different vertex layout).
    # Each low vertex's +Z ray should land on the cage at z=2.
    low = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
    low_n = np.tile([0.0, 0.0, 1.0], (4, 1))
    cage_pts = np.array(
        [[-1, -1, 2], [2, -1, 2], [2, 2, 2], [-1, 2, 2]], dtype=np.float64
    )
    cage_tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    out = cage.resample_cage(low, low_n, cage_pts, cage_tris)
    assert np.allclose(out[:, 2], 2.0), out
    assert np.allclose(out[:, :2], low[:, :2])  # x,y unchanged (ray is axis-aligned)


def test_resample_cage_miss_falls_back_to_nearest():
    # A low vertex whose +Z ray misses the (small, off-to-the-side) cage falls back to the
    # nearest cage point rather than staying at the low vertex.
    low = np.array([[5.0, 5.0, 0.0]], dtype=np.float64)
    low_n = np.array([[0.0, 0.0, 1.0]])
    cage_pts = np.array([[0, 0, 1], [0.2, 0, 1], [0.2, 0.2, 1], [0, 0.2, 1]], dtype=np.float64)
    cage_tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    out = cage.resample_cage(low, low_n, cage_pts, cage_tris)
    assert not np.allclose(out[0], low[0])          # it moved off the low vertex
    assert np.linalg.norm(out[0] - [0.2, 0.2, 1.0]) < 0.3  # near the cage corner


def test_blend_normals_opposed_falls_back_to_soft():
    # hard == -soft cancels at the midpoint; result should fall back to the soft normal.
    hard = np.array([[0.0, 0.0, 1.0]])
    soft = np.array([[0.0, 0.0, -1.0]])
    out = cage.blend_normals(hard, soft, 0.5)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)
    assert np.allclose(out, soft)
