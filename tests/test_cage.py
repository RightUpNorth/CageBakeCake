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


def test_blend_normals_opposed_falls_back_to_soft():
    # hard == -soft cancels at the midpoint; result should fall back to the soft normal.
    hard = np.array([[0.0, 0.0, 1.0]])
    soft = np.array([[0.0, 0.0, -1.0]])
    out = cage.blend_normals(hard, soft, 0.5)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)
    assert np.allclose(out, soft)
