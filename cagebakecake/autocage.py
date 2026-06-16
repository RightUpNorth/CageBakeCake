"""Auto-solve the bake cage: compute a per-vertex offset field that encloses the high
poly so the bake has no poke-through, kept smooth and near-minimal.

The cage offset at a vertex is the distance `d` the cage rides out from the base along the
firing normal. A bake ray starts at the cage point and sweeps inward through the surface
and an equal distance beyond - the band `[surf - d, surf + d]` along the normal - taking
the first high-poly hit (see `bake.bake`). So a texel is captured iff the nearest high
surface in its normal column lies within +/- d of the surface: the cage must enclose the
worst protrusion (the orange poke-through miss) and reach the deepest recess. The solver
finds the smallest such `d` per vertex.

Three stages, each monotone toward "more enclosing" so the cage never loses coverage:

1. Probe (per vertex): cast a ray out and in along the normal; the nearest high surface in
   that column is the offset the vertex needs. Fast - one pair of rays per vertex - but
   blind to detail that pokes through a triangle interior between vertices.
2. Smooth upward: relax the field toward each vertex's neighbour average, but never below
   its own required floor, so the cage stops spiking without un-enclosing anything.
3. Verify and relax: bake at a low resolution, read the per-face poke-through class
   (`bake.bake(return_face_miss=True)`), and grow the offending faces' vertices. This is
   what closes the triangle-interior protrusions the per-vertex probe cannot see. Repeat
   until no face pokes through (or a round budget is spent).

GL-free and pure (numpy + trimesh), so it unit-tests headlessly and runs on the bake
worker thread. v1 solves the offset magnitude only; bending the firing direction for
overhangs (the cage already supports per-vertex skew) is a later pass. See
docs/feature-gaps.md.
"""

from __future__ import annotations

import numpy as np

from . import bake


def build_adjacency(n: int, low_tris: np.ndarray) -> list:
    """Per-vertex unique neighbour ids from the triangulation (mirrors
    `CageEditor._get_adjacency`); drives the upward smoothing."""
    sets = [set() for _ in range(n)]
    for a, b, c in np.asarray(low_tris, dtype=np.int64):
        sets[a].update((int(b), int(c)))
        sets[b].update((int(a), int(c)))
        sets[c].update((int(a), int(b)))
    return [np.fromiter(s, dtype=np.int64) for s in sets]


def _nearest_hit_dist(ray_mesh, origins, dirs, search, eps):
    """Distance to the nearest high-poly hit from each origin along `dirs`, within
    `search`; np.inf where the ray finds nothing. Origins are nudged forward by `eps` so a
    vertex sitting on the high surface does not self-hit at distance zero."""
    o = np.asarray(origins, dtype=np.float64) + dirs * eps
    loc, ray_idx, _tri = ray_mesh.ray.intersects_location(
        ray_origins=o, ray_directions=dirs, multiple_hits=False)
    dist = np.full(len(o), np.inf)
    if len(ray_idx):
        d = np.linalg.norm(loc - o[ray_idx], axis=1) + eps
        keep = d <= search
        np.minimum.at(dist, ray_idx[keep], d[keep])
    return dist


def probe_protrusion(low_points, firing_normals, ray_mesh, search, eps):
    """Per-vertex required offset: the distance to the nearest high surface in the vertex's
    normal column. Prefers the outward wall (the first surface a bake ray meets scanning in
    from outside); falls back to the inward wall when the column has high poly only below.
    Returns (needed (N,), has_high (N,) bool); needed is 0 where the column is empty."""
    n = np.asarray(firing_normals, dtype=np.float64)
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
    out = _nearest_hit_dist(ray_mesh, low_points, n, search, eps)
    inw = _nearest_hit_dist(ray_mesh, low_points, -n, search, eps)
    needed = np.where(np.isfinite(out), out, inw)
    has_high = np.isfinite(needed)
    return np.where(has_high, needed, 0.0), has_high


def _smooth_up(d, floor, adjacency, iters, lam):
    """Laplacian-relax `d` toward each vertex's neighbour average, clamped to never drop
    below `floor` - smooths the field without ever un-enclosing the high poly."""
    d = np.asarray(d, dtype=np.float64).copy()
    for _ in range(int(iters)):
        nb = np.array([d[a].mean() if len(a) else d[i]
                       for i, a in enumerate(adjacency)])
        d = np.maximum(floor, (1.0 - lam) * d + lam * nb)
    return d


def solve_offsets(low_points, low_tris, firing_normals, high_points, high_tris, *,
                  base_points=None, low_uvs=None, low_normals=None, high_normals=None,
                  ray_mesh=None, default_push=None, adjacency=None,
                  margin=0.05, search_frac=0.5, smooth_iters=10, lam=0.5,
                  max_rounds=4, growth=1.6, resolution=256, progress=None):
    """Solve a per-vertex cage offset `d` (distance from base along the firing normal) that
    encloses the high poly. Returns the offset array (N,).

    `base_points` defaults to the low poly (cage rest = low surface). When `low_uvs`,
    `low_normals` and `high_normals` are given (and `max_rounds` > 0) the verify-and-relax
    loop runs a real low-resolution bake to drive poke-through to zero; without them the
    result is the probe + smoothing estimate only. `default_push` is the offset kept for
    vertices whose column has no high poly (so the cage there does not collapse to the
    surface); it defaults to 3% of the low-poly bbox diagonal."""
    notify = progress or (lambda _m: None)
    low_points = np.asarray(low_points, dtype=np.float64)
    normals = np.asarray(firing_normals, dtype=np.float64)
    normals = normals / (np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12)
    base = low_points if base_points is None else np.asarray(base_points, dtype=np.float64)
    n = len(low_points)
    diag = float(np.linalg.norm(np.ptp(low_points, axis=0))) or 1.0
    eps = diag * 1e-5 + 1e-9
    search = diag * float(search_frac)
    if ray_mesh is None:
        ray_mesh = bake.make_ray_mesh(high_points, high_tris)
    if adjacency is None:
        adjacency = build_adjacency(n, low_tris)

    needed, has_high = probe_protrusion(low_points, normals, ray_mesh, search, eps)
    notify(f"probed {int(has_high.sum())}/{n} vertices with high poly in column")
    floor = np.where(has_high, needed * (1.0 + margin) + eps, 0.0)
    dp = (diag * 0.03) if default_push is None else float(default_push)
    d = np.where(has_high, floor, dp)
    d = _smooth_up(d, floor, adjacency, smooth_iters, lam)

    can_verify = (low_uvs is not None and low_normals is not None
                  and high_normals is not None and int(max_rounds) > 0)
    if can_verify:
        low_normals = np.asarray(low_normals, dtype=np.float64)
        high_normals = np.asarray(high_normals, dtype=np.float64)
        for r in range(int(max_rounds)):
            cage_pts = base + normals * d[:, None]
            _img, _miss, face_class = bake.bake(
                low_points, low_tris, low_normals, low_uvs, cage_pts,
                high_points, high_tris, high_normals, resolution=resolution,
                firing_normals=normals, return_miss=True, return_face_miss=True,
                ray_mesh=ray_mesh)
            poke = np.nonzero(np.asarray(face_class) == 1)[0]
            notify(f"verify round {r + 1}: {len(poke)} poke-through faces")
            if len(poke) == 0:
                break
            verts = np.unique(low_tris[poke])
            floor[verts] = floor[verts] * float(growth) + diag * 0.01
            d = np.maximum(d, floor)
            d = _smooth_up(d, floor, adjacency, smooth_iters, lam)
    return d


def solve_manual_delta(d, firing_normals, global_push):
    """Convert a solved offset field `d` into the editor's `manual_delta` (a per-vertex 3D
    edit). The cage composes as base + normals*global_push + manual_delta, and the solver
    wants base + normals*d, so manual_delta = normals * (d - global_push)."""
    n = np.asarray(firing_normals, dtype=np.float64)
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
    return n * (np.asarray(d, dtype=np.float64) - float(global_push))[:, None]
