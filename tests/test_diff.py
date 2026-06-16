"""Headless tests for the before/after difference heatmap (feature-gap D)."""

from __future__ import annotations

import numpy as np
import pytest

from cagebakecake import bake


def test_identical_maps_diff_to_black():
    img = np.full((8, 8, 3), 100, np.uint8)
    d = bake.diff_map(img, img)
    assert d.shape == (8, 8, 3)
    assert np.all(d == 0)


def test_difference_brightens_with_divergence():
    a = np.zeros((8, 8, 3), np.uint8)
    b = np.full((8, 8, 3), 40, np.uint8)
    small = bake.diff_map(a, b, gain=1.0)
    big = bake.diff_map(a, b, gain=4.0)
    assert big.mean() > small.mean() > 0
    assert np.all(big[..., 0] == big[..., 1]) and np.all(big[..., 1] == big[..., 2])  # grey


def test_diff_clips_and_ignores_alpha():
    a = np.zeros((4, 4, 4), np.uint8)
    b = np.full((4, 4, 4), 255, np.uint8)  # alpha present but ignored
    d = bake.diff_map(a, b, gain=10.0)
    assert np.all(d == 255)  # fully divergent, clipped to white


def test_diff_rejects_mismatched_sizes():
    with pytest.raises(ValueError):
        bake.diff_map(np.zeros((4, 4, 3), np.uint8), np.zeros((8, 8, 3), np.uint8))
