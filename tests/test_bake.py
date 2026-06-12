"""Headless bake tests on a synthetic known pair (no window, no asset files).

The low poly is a unit quad in the z=0 plane; the high poly is a parallel quad at
z=0.5 covered by a cage at z=1.0. With matching normals the bake is flat
(128,128,255); tilting the high-poly normal pushes the encoded channel the expected
way. See docs/baking.md.
"""

from __future__ import annotations

import numpy as np
import pytest

from cagebakecake import bake


def _low_quad():
    """Unit quad in z=0, normals +Z, UVs = xy. Returns (points, tris, normals, uvs)."""
    points = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64
    )
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    uvs = uv[tris]  # (F,3,2) per-corner
    return points, tris, normals, uvs


def _high_quad(normal):
    """Quad at z=0.5 spanning slightly past the unit square so every ray hits, with a
    uniform vertex normal."""
    points = np.array(
        [[-0.1, -0.1, 0.5], [1.1, -0.1, 0.5], [1.1, 1.1, 0.5], [-0.1, 1.1, 0.5]],
        dtype=np.float64,
    )
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    normals = np.tile(np.asarray(normal, dtype=np.float64), (4, 1))
    return points, tris, normals


def _cage(low_points, offset=1.0):
    return low_points + np.array([0.0, 0.0, offset])


def test_flat_high_bakes_flat_blue():
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad([0.0, 0.0, 1.0])
    img = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32)

    assert img.shape == (32, 32, 3)
    # Covered texels (interior, away from UV-edge rounding) encode the flat normal.
    interior = img[4:28, 4:28]
    assert np.allclose(interior, bake.FLAT_RGB, atol=2), interior.reshape(-1, 3)


def test_tilted_high_normal_pushes_red_channel():
    lp, lt, ln, luv = _low_quad()
    tilt = np.array([1.0, 0.0, 1.0]) / np.sqrt(2.0)  # leans toward +X (the U tangent)
    hp, ht, hn = _high_quad(tilt)
    img = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32)

    interior = img[4:28, 4:28].reshape(-1, 3)
    r, g, b = interior.mean(axis=0)
    assert r > 150  # +X tilt raises red
    assert abs(g - 128) <= 3  # nothing pushes green
    assert b > 150  # normal still mostly out of the surface


def test_skew_firing_does_not_distort_encode():
    # The firing direction (skew, M8.2) aims the rays, but the map is encoded in the
    # shading-normal frame. Tilt the firing direction; with a flat +Z high poly and +Z
    # shading normals the interior must still encode flat blue (it would push red if the
    # encode wrongly used the tilted firing direction).
    lp, lt, ln, luv = _low_quad()  # shading normals +Z
    hp, ht, hn = _high_quad([0.0, 0.0, 1.0])  # high normal +Z, spans past the unit square
    firing = np.tile(np.array([0.6, 0.0, 0.8]), (4, 1))  # tilted toward +X
    img = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32,
                    firing_normals=firing)
    interior = img[6:26, 6:26]
    assert np.allclose(interior, bake.FLAT_RGB, atol=3), interior.reshape(-1, 3).mean(0)


def test_misses_stay_flat():
    # Cage thinner than the gap to the high poly -> every ray falls short -> all flat.
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad([0.0, 0.0, 1.0])
    thin_cage = _cage(lp, offset=0.1)  # reaches z in [0.1, -0.1]; high is at z=0.5
    img = bake.bake(lp, lt, ln, luv, thin_cage, hp, ht, hn, resolution=16)
    assert np.all(img == bake.FLAT_RGB)


def test_supersample_keeps_flat_and_size():
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad([0.0, 0.0, 1.0])
    img = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32, supersample=2)
    assert img.shape == (32, 32, 3)
    interior = img[6:26, 6:26]
    assert np.allclose(interior, bake.FLAT_RGB, atol=2), interior.reshape(-1, 3).mean(0)


def test_padding_bleeds_island_colour_into_background():
    # UV island in the lower-left quarter; the rest is background. A tilted high normal
    # makes the island reddish so padding is detectable.
    lp, lt, ln, _ = _low_quad()
    uv = np.array([[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]], dtype=np.float64)
    luv = uv[lt]
    tilt = np.array([1.0, 0.0, 1.0]) / np.sqrt(2.0)
    hp, ht, hn = _high_quad(tilt)
    no = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32, padding=0)
    pad = bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=32, padding=4)

    bg = (20, 18)  # just right of the island edge (~col 16), within 4 texels
    assert np.array_equal(no[bg], bake.FLAT_RGB)   # background is flat without padding
    assert not np.array_equal(no[bg], pad[bg])      # padding changed it
    assert pad[bg][0] > 150                          # filled with the reddish island colour


def test_no_uvs_raises():
    lp, lt, ln, _ = _low_quad()
    hp, ht, hn = _high_quad([0.0, 0.0, 1.0])
    with pytest.raises(ValueError, match="no usable UVs"):
        bake.bake(lp, lt, ln, np.empty((0,)), _cage(lp), hp, ht, hn, resolution=8)


def test_writes_png(tmp_path):
    lp, lt, ln, luv = _low_quad()
    hp, ht, hn = _high_quad([0.0, 0.0, 1.0])
    out = tmp_path / "normal.png"
    bake.bake(lp, lt, ln, luv, _cage(lp), hp, ht, hn, resolution=16, out_path=str(out))
    assert out.exists() and out.stat().st_size > 0
