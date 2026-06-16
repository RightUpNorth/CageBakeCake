"""Headless tests for ray-miss classification (no window).

The miss map (and the per-face class for the 3D overlay) now splits a missed texel into
too-tight poke-through (the high poly pokes out beyond the cage) and too-loose / no
surface. See feature-gap C (ray-miss feedback).
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


def _high_quad(z=0.5):
    points = np.array([[-0.1, -0.1, z], [1.1, -0.1, z], [1.1, 1.1, z], [-0.1, 1.1, z]],
                      dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    return points, tris, normals


def _cage(low_points, offset):
    return low_points + np.array([0.0, 0.0, offset])


def _dominant(pixel_block):
    return np.argmax(pixel_block.reshape(-1, 3).mean(axis=0))  # 0=R, 1=G, 2=B


def test_poke_through_reads_orange_and_classes_face_one():
    # Cage at z=0.3 sits *inside* the high poly at z=0.5: rays miss inward but the high
    # poly pokes out beyond the cage -> too tight (poke-through).
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad(z=0.5)
    img, miss, face = bake.bake(lp, lt, ln, luv, _cage(lp, 0.3), hp, ht, hn,
                                resolution=16, return_miss=True, return_face_miss=True)
    interior = miss[4:12, 4:12].reshape(-1, 3)
    r, g, b = interior.mean(axis=0)
    assert r > g and r > b            # orange leans red/green high, blue low
    assert g > b                      # ... and orange has more green than blue
    assert set(np.unique(face).tolist()) == {1}   # every face flagged poke-through


def test_too_loose_reads_red_and_classes_face_two():
    # Thin cage that never reaches the high poly, which is also far away -> too loose.
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad(z=5.0)
    img, miss, face = bake.bake(lp, lt, ln, luv, _cage(lp, 0.05), hp, ht, hn,
                                resolution=16, return_miss=True, return_face_miss=True)
    interior = miss[4:12, 4:12].reshape(-1, 3)
    assert _dominant(interior) == 0               # red dominant
    assert set(np.unique(face).tolist()) == {2}   # every face flagged too-loose


def test_hits_keep_face_class_zero_and_green():
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad(z=0.5)
    img, miss, face = bake.bake(lp, lt, ln, luv, _cage(lp, 1.0), hp, ht, hn,
                                resolution=16, return_miss=True, return_face_miss=True)
    interior = miss[4:12, 4:12].reshape(-1, 3)
    assert _dominant(interior) == 1               # green dominant
    assert np.all(face == 0)                       # nothing missed


def test_face_miss_class_poke_overrides_loose():
    # face 0 has a poke texel and a loose texel; face 1 only loose.
    tri_index = np.array([0, 0, 1])
    hit_mask = np.array([False, False, False])
    poke = np.array([True, False, False])
    cls = bake._face_miss_class(2, tri_index, hit_mask, poke)
    assert cls[0] == 1  # poke wins on face 0
    assert cls[1] == 2  # loose on face 1
