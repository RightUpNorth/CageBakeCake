"""Headless tests for the height/displacement and world-position bakes (feature-gap C)."""

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
    return points, tris


def _cage(low_points, offset=1.0):
    return low_points + np.array([0.0, 0.0, offset])


def test_height_outside_surface_reads_above_mid_grey():
    lp, lt, ln, luv = _low_quad()
    hp, ht = _high_quad(z=0.5)
    # value_range = 1.0 (the cage offset); a hit at +0.5 along the normal -> 0.5+0.5*0.5 = 0.75.
    img = bake.bake_height(lp, lt, ln, luv, _cage(lp, 1.0), hp, ht, resolution=32,
                           value_range=1.0)
    interior = img[6:26, 6:26].reshape(-1, 3)
    assert np.all(interior[:, 0] == interior[:, 1])           # grayscale
    assert abs(interior[:, 0].mean() - 0.75 * 255) < 8        # ~0.75 grey


def _half_uvs(lt):
    # UVs in [0, 0.5]^2 so only the bottom-left image quarter is covered, leaving the
    # top-right corner as uncovered background.
    uv = np.array([[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]], dtype=np.float64)
    return uv[lt]


def test_height_background_is_mid_grey():
    lp, lt, ln, _ = _low_quad()
    hp, ht = _high_quad(z=0.5)
    img = bake.bake_height(lp, lt, ln, _half_uvs(lt), _cage(lp, 1.0), hp, ht,
                           resolution=16, value_range=1.0)
    assert img[0, -1, 0] == 128   # uncovered top-right corner stays mid-grey


def test_position_encodes_normalized_hit_location():
    lp, lt, ln, luv = _low_quad()
    hp, ht = _high_quad(z=0.5)
    img = bake.bake_position(lp, lt, ln, luv, _cage(lp, 1.0), hp, ht, resolution=64)
    interior = img[10:54, 10:54].reshape(-1, 3).mean(axis=0)
    # The high quad spans x,y in [-0.1,1.1] (z constant); the unit-square hits map to the
    # middle of that range -> ~mid grey in R/G, and z is the bbox min so B is ~0 (or 255).
    assert 60 < interior[0] < 195 and 60 < interior[1] < 195


def test_position_background_is_black():
    lp, lt, ln, _ = _low_quad()
    hp, ht = _high_quad(z=0.5)
    img = bake.bake_position(lp, lt, ln, _half_uvs(lt), _cage(lp, 1.0), hp, ht,
                             resolution=16)
    assert np.all(img[0, -1] == 0)   # uncovered top-right corner stays black


def test_extra_maps_are_bakeable_kinds():
    from cagebakecake import recipe
    assert "height" in recipe.BAKEABLE_KINDS
    assert "position" in recipe.BAKEABLE_KINDS
