"""Headless tests for the object-space normal bake and the flip-green output option.

See feature-gap C (more map types / output options).
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


def _high_quad(normal, z=0.5):
    points = np.array([[-0.1, -0.1, z], [1.1, -0.1, z], [1.1, 1.1, z], [-0.1, 1.1, z]],
                      dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile(np.asarray(normal, dtype=np.float64), (4, 1))
    return points, tris, normals


def _cage(low_points, offset=1.0):
    return low_points + np.array([0.0, 0.0, offset])


def test_object_space_encodes_world_normal_directly():
    # A high poly whose normal points +Y -> object-space encodes (128,255,128).
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad([0.0, 1.0, 0.0])
    img = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32, space="object")
    interior = img[6:26, 6:26].reshape(-1, 3).mean(axis=0)
    r, g, b = interior
    assert abs(r - 128) < 6 and abs(b - 128) < 6   # x,z near zero -> mid grey
    assert g > 240                                  # +Y world normal -> green pinned high


def test_object_ignores_tangent_frame_unlike_tangent_space():
    # UVs where U follows world +Y: the tangent frame is rotated from world, so a +Y world
    # normal encodes green in object space but red (along the U tangent) in tangent space.
    lp = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
    lt = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    ln = np.tile([0.0, 0.0, 1.0], (4, 1))
    uv = np.array([[0, 0], [0, 1], [1, 1], [1, 0]], dtype=np.float64)  # U <- world +Y
    luv = uv[lt]
    hp, ht, hn = _high_quad([0.0, 1.0, 0.0])
    obj = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32, space="object")
    tan = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32, space="tangent")
    assert not np.array_equal(obj, tan)
    assert obj[6:26, 6:26, 1].mean() > 240   # object: green (world +Y)
    assert tan[6:26, 6:26, 0].mean() > 200   # tangent: red (Y is the U tangent here)


def test_flip_green_inverts_only_green():
    img = np.dstack([
        np.full((4, 4), 10, np.uint8),
        np.full((4, 4), 30, np.uint8),
        np.full((4, 4), 200, np.uint8),
    ])
    out = bake.flip_green(img)
    assert np.all(out[..., 0] == 10)        # red untouched
    assert np.all(out[..., 1] == 225)       # green inverted (255-30)
    assert np.all(out[..., 2] == 200)       # blue untouched
    assert out is not img                    # returns a copy


def test_flip_green_is_its_own_inverse():
    img = (np.random.default_rng(0).integers(0, 256, (8, 8, 3))).astype(np.uint8)
    np.testing.assert_array_equal(bake.flip_green(bake.flip_green(img)), img)
