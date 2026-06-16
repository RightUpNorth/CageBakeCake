"""Headless tests for the cage auto-solver (autocage). A high-poly bump pokes through a
flat cage; the solver must inflate the cage just enough to enclose it - verified by baking
the solved cage and asserting zero poke-through faces. See docs/feature-gaps.md."""

from __future__ import annotations

import numpy as np

from cagebakecake import autocage, bake


def _grid(nx, ny, zfun):
    """A triangulated grid over the unit square at heights `zfun(x, y)`. Returns
    (points (V,3), tris (F,3), uv (V,2)) with UV = the xy position."""
    xs = np.linspace(0.0, 1.0, nx)
    ys = np.linspace(0.0, 1.0, ny)
    gx, gy = np.meshgrid(xs, ys, indexing="xy")
    pts = np.column_stack([gx.ravel(), gy.ravel(), zfun(gx, gy).ravel()]).astype(np.float64)
    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b = j * nx + i, j * nx + i + 1
            c, d = (j + 1) * nx + i, (j + 1) * nx + i + 1
            tris.append([a, b, d])
            tris.append([a, d, c])
    uv = np.column_stack([gx.ravel(), gy.ravel()]).astype(np.float64)
    return pts, np.array(tris, dtype=np.int64), uv


def _up(n):
    return np.tile([0.0, 0.0, 1.0], (n, 1)).astype(np.float64)


def _bump(x, y):
    return np.exp(-(((x - 0.5) ** 2 + (y - 0.5) ** 2) / 0.05))


def _poke_faces(lp, lt, ln, luvc, cage_pts, hp, ht, hn, res=128):
    _img, _miss, fc = bake.bake(lp, lt, ln, luvc, cage_pts, hp, ht, hn, resolution=res,
                                firing_normals=ln, return_miss=True, return_face_miss=True)
    return int((np.asarray(fc) == 1).sum())


def _scene(height=0.3):
    lp, lt, uv = _grid(7, 7, lambda x, y: np.zeros_like(x))
    hp, ht, _ = _grid(21, 21, lambda x, y: height * _bump(x, y))
    ln, hn = _up(len(lp)), _up(len(hp))
    return lp, lt, ln, uv[lt], hp, ht, hn


def test_flat_cage_pokes_through():
    """Sanity: a barely-offset cage really does miss the bump (so the solve test means
    something)."""
    lp, lt, ln, luvc, hp, ht, hn = _scene(0.3)
    flat = lp + ln * 0.01
    assert _poke_faces(lp, lt, ln, luvc, flat, hp, ht, hn) > 0


def test_solver_encloses_the_bump():
    lp, lt, ln, luvc, hp, ht, hn = _scene(0.3)
    d = autocage.solve_offsets(lp, lt, ln, hp, ht, low_uvs=luvc, low_normals=ln,
                               high_normals=hn, resolution=128)
    cage_pts = lp + ln * d[:, None]
    assert _poke_faces(lp, lt, ln, luvc, cage_pts, hp, ht, hn) == 0


def test_offset_tracks_protrusion():
    """The cage is tall where the bump is tall and near-flat at the corners (near-minimal,
    not a uniform inflation)."""
    lp, lt, ln, luvc, hp, ht, hn = _scene(0.3)
    d = autocage.solve_offsets(lp, lt, ln, hp, ht, low_uvs=luvc, low_normals=ln,
                               high_normals=hn, resolution=128)
    center = int(np.argmin(np.linalg.norm(lp[:, :2] - [0.5, 0.5], axis=1)))
    corner = int(np.argmin(np.linalg.norm(lp[:, :2] - [0.0, 0.0], axis=1)))
    assert d[center] >= 0.3          # encloses the full bump height (+ margin)
    assert d[corner] < 0.5 * d[center]


def test_probe_only_estimate_is_cheap_and_enclosing_at_vertices():
    """With the verify loop off (max_rounds=0) the per-vertex probe still covers protrusion
    sampled directly along a vertex column."""
    lp, lt, ln, luvc, hp, ht, hn = _scene(0.3)
    d = autocage.solve_offsets(lp, lt, ln, hp, ht, max_rounds=0)
    center = int(np.argmin(np.linalg.norm(lp[:, :2] - [0.5, 0.5], axis=1)))
    assert d[center] >= 0.3


def test_solve_manual_delta_round_trips():
    lp, lt, ln, _luvc, hp, ht, _hn = _scene(0.3)
    d = autocage.solve_offsets(lp, lt, ln, hp, ht, max_rounds=0)
    gp = 0.05
    md = autocage.solve_manual_delta(d, ln, gp)
    cage = lp + ln * gp + md                # compose(base, normals, push, manual_delta)
    np.testing.assert_allclose(cage, lp + ln * d[:, None], atol=1e-9)
