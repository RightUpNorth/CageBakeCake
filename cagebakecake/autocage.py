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
worker thread. `solve_offsets` solves the offset magnitude along a fixed firing direction;
`solve` may additionally bend the firing direction toward the nearest high surface on the
faces that keep poking through (clamped to a max tilt angle), so the cage captures
overhangs a pure-normal offset cannot reach. See docs/feature-gaps.md.
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


def _nlerp(a, b, t):
    """Per-vertex normalized linear interpolation from unit `a` to unit `b` by `t` (a (N,)
    fraction). A cheap stand-in for slerp - close enough over the moderate tilt angles the
    aim stays clamped to, and it never produces a zero vector for non-antipodal inputs."""
    t = np.asarray(t, dtype=np.float64)[:, None]
    v = a * (1.0 - t) + b * t
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)


def _clamp_to_cone(base, target, max_deg):
    """Limit each `target` direction to within `max_deg` of `base` (both unit), so the aimed
    firing direction stays a bounded tilt off the normal rather than a wild flip."""
    cos = np.clip(np.sum(base * target, axis=1), -1.0, 1.0)
    ang = np.arccos(cos)
    maxr = np.radians(float(max_deg))
    frac = np.where(ang > 1e-9, np.minimum(1.0, maxr / np.maximum(ang, 1e-9)), 0.0)
    return _nlerp(base, target, frac)


def aim_targets(high_points, high_normals, low_points, base_firing, max_tilt_deg):
    """Per-vertex firing direction aimed along the nearest high-poly vertex normal, so a
    bake ray meets an overhang head-on instead of grazing past it. Kept in the same
    hemisphere as the base firing (the cage sits outside) and clamped to `max_tilt_deg`. The
    nearest high vertex is found with a KD-tree (scipy) - no proximity/rtree dependency."""
    from scipy.spatial import cKDTree

    base = np.asarray(base_firing, dtype=np.float64)
    base = base / (np.linalg.norm(base, axis=1, keepdims=True) + 1e-12)
    tree = cKDTree(np.asarray(high_points, dtype=np.float64))
    _dist, idx = tree.query(np.asarray(low_points, dtype=np.float64))
    fn = np.asarray(high_normals, dtype=np.float64)[idx].copy()
    fn = fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
    flip = np.sum(fn * base, axis=1) < 0.0
    fn[flip] *= -1.0
    return _clamp_to_cone(base, fn, max_tilt_deg)


def solve(low_points, low_tris, firing_normals, high_points, high_tris, *,
          base_points=None, low_uvs=None, low_normals=None, high_normals=None,
          ray_mesh=None, default_push=None, adjacency=None,
          margin=0.05, search_frac=0.5, smooth_iters=10, lam=0.5,
          max_rounds=6, growth=1.6, resolution=256,
          max_tilt_deg=60.0, aim_strength=1.0, progress=None):
    """Solve the cage so it encloses the high poly, returning
    ``{"offsets": d (N,), "firing": (N,3)}``: the per-vertex offset (distance from base
    along the firing direction) and the per-vertex firing direction the offsets are measured
    along.

    With `max_tilt_deg` > 0 (and `high_normals` given) the solver first aims each firing
    direction toward the nearest high-poly surface normal, scaled by `aim_strength` and
    clamped to `max_tilt_deg`, so rays meet steep / overhanging detail head-on instead of
    grazing past it (the classic aimed cage). The aim self-limits to ~0 on flat regions
    (the nearest surface normal there already matches the cage normal). It does not touch the
    encode frame (the hard shading normals), so the baked map stays undistorted. With
    `max_tilt_deg` = 0 (or `aim_strength` = 0) the firing is returned unchanged and this is
    the pure-magnitude solve.

    The magnitude is then solved along that fixed firing: a per-vertex protrusion probe,
    upward smoothing, and - when `low_uvs`, `low_normals`, `high_normals` are given and
    `max_rounds` > 0 - a verify-and-relax loop that bakes at low resolution and grows the
    faces that still poke through until none do. `base_points` defaults to the low poly.
    `default_push` is the offset kept where a vertex column has no high poly (so the cage
    does not collapse); it defaults to 3% of the low-poly bbox diagonal."""
    notify = progress or (lambda _m: None)
    low_points = np.asarray(low_points, dtype=np.float64)
    base_firing = np.asarray(firing_normals, dtype=np.float64)
    base_firing = base_firing / (np.linalg.norm(base_firing, axis=1, keepdims=True) + 1e-12)
    base = low_points if base_points is None else np.asarray(base_points, dtype=np.float64)
    n = len(low_points)
    diag = float(np.linalg.norm(np.ptp(low_points, axis=0))) or 1.0
    eps = diag * 1e-5 + 1e-9
    search = diag * float(search_frac)
    if ray_mesh is None:
        ray_mesh = bake.make_ray_mesh(high_points, high_tris)
    if adjacency is None:
        adjacency = build_adjacency(n, low_tris)

    # Aim the firing toward the nearest high surface (the overhang-capturing tilt). Needs the
    # high-poly normals; without them it is a pure-magnitude solve (firing unchanged).
    tilt_on = (float(max_tilt_deg) > 0.0 and float(aim_strength) > 0.0
               and high_normals is not None)
    if tilt_on:
        targets = aim_targets(high_points, high_normals, low_points, base_firing, max_tilt_deg)
        firing = _nlerp(base_firing, targets, np.full(n, float(aim_strength)))
        tilted = np.degrees(np.arccos(np.clip(np.sum(firing * base_firing, axis=1), -1, 1)))
        notify(f"aimed firing toward nearest high surface (max tilt {tilted.max():.0f} deg)")
    else:
        firing = base_firing.copy()

    needed, has_high = probe_protrusion(low_points, firing, ray_mesh, search, eps)
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
            cage_pts = base + firing * d[:, None]
            _img, _miss, face_class = bake.bake(
                low_points, low_tris, low_normals, low_uvs, cage_pts,
                high_points, high_tris, high_normals, resolution=resolution,
                firing_normals=firing, return_miss=True, return_face_miss=True,
                ray_mesh=ray_mesh)
            poke = np.nonzero(np.asarray(face_class) == 1)[0]
            notify(f"verify round {r + 1}: {len(poke)} poke-through faces")
            if len(poke) == 0:
                break
            verts = np.unique(low_tris[poke])
            floor[verts] = floor[verts] * float(growth) + diag * 0.01
            d = np.maximum(d, floor)
            d = _smooth_up(d, floor, adjacency, smooth_iters, lam)
    return {"offsets": d, "firing": firing}


def solve_offsets(low_points, low_tris, firing_normals, high_points, high_tris, *,
                  max_rounds=4, **kwargs):
    """Pure-magnitude solve (no firing tilt): the v1 entry point, kept for callers and tests
    that only want the offset field. Delegates to `solve` with `max_tilt_deg=0`."""
    return solve(low_points, low_tris, firing_normals, high_points, high_tris,
                 max_rounds=max_rounds, max_tilt_deg=0.0, **kwargs)["offsets"]


def solve_manual_delta(d, firing_normals, global_push):
    """Convert a solved offset field `d` into the editor's `manual_delta` (a per-vertex 3D
    edit). The cage composes as base + normals*global_push + manual_delta, and the solver
    wants base + normals*d, so manual_delta = normals * (d - global_push)."""
    n = np.asarray(firing_normals, dtype=np.float64)
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
    return n * (np.asarray(d, dtype=np.float64) - float(global_push))[:, None]
