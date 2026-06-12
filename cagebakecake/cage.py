"""Headless cage math (no plotting).

The cage is assumed to be a topology-matched duplicate of the low poly: same vertex
count and order, so cage vertex i corresponds to low-poly vertex i and is pushed
along low-poly normal i. See docs/cage-model.md.
"""

from __future__ import annotations

import numpy as np


def validate_correspondence(low_points: np.ndarray, cage_points: np.ndarray) -> None:
    """Raise if the cage is not a vertex-for-vertex match of the low poly."""
    if len(low_points) != len(cage_points):
        raise ValueError(
            "cage/low-poly vertex count mismatch: "
            f"low={len(low_points)} cage={len(cage_points)} "
            "(cage must be a topology-matched duplicate; see docs/cage-model.md)"
        )


def displace(base_points: np.ndarray, normals: np.ndarray, value: float) -> np.ndarray:
    """Push base points outward along normals by a scalar value."""
    return base_points + normals * float(value)


def compose(
    base_points: np.ndarray,
    normals: np.ndarray,
    value: float,
    manual_delta: np.ndarray,
) -> np.ndarray:
    """Cage position = base + global normal push + per-vertex manual edits.

    This is the single composition both the displacement slider and the gizmo write
    through, so neither clobbers the other (see docs/cage-model.md).
    """
    return base_points + normals * float(value) + manual_delta


def closest_point_on_axis(
    ray_o: np.ndarray, ray_d: np.ndarray, anchor: np.ndarray, axis: np.ndarray
) -> np.ndarray:
    """Point on the line (anchor + s*axis) closest to the cursor ray (ray_o + t*ray_d).

    Used to drag a vertex along its normal: project the cursor ray onto the normal
    line and return the resulting point on that line.
    """
    ray_o = np.asarray(ray_o, dtype=np.float64)
    u = np.asarray(axis, dtype=np.float64)
    u = u / np.linalg.norm(u)
    v = np.asarray(ray_d, dtype=np.float64)
    v = v / np.linalg.norm(v)
    anchor = np.asarray(anchor, dtype=np.float64)
    w0 = anchor - ray_o
    b = float(u @ v)
    denom = 1.0 - b * b
    if abs(denom) < 1e-9:  # ray parallel to axis
        return anchor.copy()
    d = float(u @ w0)
    e = float(v @ w0)
    s = (b * e - d) / denom
    return anchor + u * s


def ray_plane_intersect(
    ray_o: np.ndarray, ray_d: np.ndarray, anchor: np.ndarray, normal: np.ndarray
) -> np.ndarray:
    """Intersection of the cursor ray with the tangent plane through anchor.

    Used to slide a vertex across the surface: where the cursor ray meets the plane
    perpendicular to the normal at anchor.
    """
    ray_o = np.asarray(ray_o, dtype=np.float64)
    v = np.asarray(ray_d, dtype=np.float64)
    v = v / np.linalg.norm(v)
    anchor = np.asarray(anchor, dtype=np.float64)
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    denom = float(v @ n)
    if abs(denom) < 1e-9:  # ray parallel to plane
        return anchor.copy()
    t = float((anchor - ray_o) @ n) / denom
    return ray_o + v * t


def soft_weights(
    points: np.ndarray, center: np.ndarray, radius: float
) -> tuple[np.ndarray, np.ndarray]:
    """Proportional-editing falloff: indices within radius of center and their
    smoothstep weights (1 at the center, 0 at the radius).

    Uses euclidean distance (MVP). Caveat: this bleeds across disconnected-but-nearby
    surfaces; geodesic falloff is the correct fix later. See
    docs/milestones/milestone-1/phase-4-soft-selection.md.
    """
    points = np.asarray(points, dtype=np.float64)
    center = np.asarray(center, dtype=np.float64)
    radius = float(radius)
    d = np.linalg.norm(points - center, axis=1)
    idx = np.nonzero(d < radius)[0]
    x = np.clip(1.0 - d[idx] / radius, 0.0, 1.0)
    weights = x * x * (3.0 - 2.0 * x)  # smoothstep
    return idx, weights


def soft_vertex_normals(points: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Soft (welded) per-vertex normals for the cage push.

    Fuse coincident positions -> average the given normals per welded position ->
    assign that single normal back to every coincident point. This keeps the cage
    watertight across hard-edge / UV-seam vertex splits on the low poly (whose own
    hard normals are passed in and left untouched for baking). See docs/cage-model.md.

    On a fully welded low poly (no coincident points) every group has one vertex, so
    the input normals are returned unchanged - no change to the cage shape there.
    """
    points = np.asarray(points, dtype=np.float64)
    normals = np.asarray(normals, dtype=np.float64)
    extent = np.linalg.norm(np.ptp(points, axis=0)) or 1.0
    quant = np.round(points / (extent * 1e-6))
    _, group = np.unique(quant, axis=0, return_inverse=True)
    ngroups = int(group.max()) + 1

    acc = np.zeros((ngroups, 3))
    np.add.at(acc, group, normals)
    gnorm = acc / (np.linalg.norm(acc, axis=1, keepdims=True) + 1e-12)
    return gnorm[group]


def resample_cage(
    low_points: np.ndarray,
    low_normals: np.ndarray,
    cage_points: np.ndarray,
    cage_tris: np.ndarray,
) -> np.ndarray:
    """Resample an arbitrary (non-topology-matched) cage onto the low poly.

    For each low vertex, fire a ray outward along its normal and take the first cage
    intersection - that point becomes the topology-matched cage vertex, so the rest of
    the editor (compose, gizmo, bake) works unchanged. Low vertices whose ray misses the
    cage fall back to the nearest point on the cage surface. Returns (V,3).

    This is what lets a cage that is not a vertex-for-vertex duplicate still drive the
    tool (stretch goal: arbitrary cages).
    """
    import trimesh

    low_points = np.asarray(low_points, dtype=np.float64)
    dirs = np.asarray(low_normals, dtype=np.float64)
    dirs = dirs / (np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-12)
    mesh = trimesh.Trimesh(vertices=np.asarray(cage_points, dtype=np.float64),
                           faces=np.asarray(cage_tris, dtype=np.int64), process=False)

    result = low_points.copy()
    seen = np.zeros(len(low_points), dtype=bool)
    locs, ray_idx, _tri = mesh.ray.intersects_location(
        ray_origins=low_points, ray_directions=dirs, multiple_hits=True)
    if len(ray_idx):
        t = np.einsum("ij,ij->i", locs - low_points[ray_idx], dirs[ray_idx])
        valid = t > 1e-9
        rid, tv, lv = ray_idx[valid], t[valid], locs[valid]
        for r, p in zip(rid[np.argsort(tv)], lv[np.argsort(tv)]):
            if not seen[r]:  # first (nearest) outward hit wins
                seen[r] = True
                result[r] = p

    miss = ~seen
    if miss.any():  # rays that never met the cage: snap to the nearest cage vertex
        cp = np.asarray(cage_points, dtype=np.float64)
        d = low_points[miss][:, None, :] - cp[None, :, :]
        result[miss] = cp[np.argmin(np.einsum("ijk,ijk->ij", d, d), axis=1)]
    return result


def blend_normals(
    hard_normals: np.ndarray, soft_normals: np.ndarray, skew
) -> np.ndarray:
    """Per-vertex ray firing direction: normalize(lerp(hard, soft, skew)).

    `skew` in [0, 1] is a scalar or a per-vertex (V,) array: 0 fires along the low
    poly's hard normals, 1 along the soft (welded) copy. This is the M8.2 skew control -
    it nudges the cage push / bake ray direction without moving cage points. Where hard
    and soft are near-opposite and cancel at the blend, it falls back to the soft normal.
    See docs/milestones/milestone-8/phase-2-skew-blend.md.
    """
    hard = np.asarray(hard_normals, dtype=np.float64)
    soft = np.asarray(soft_normals, dtype=np.float64)
    s = np.asarray(skew, dtype=np.float64)
    if s.ndim == 1:
        s = s[:, None]
    blended = hard * (1.0 - s) + soft * s
    norm = np.linalg.norm(blended, axis=1, keepdims=True)
    bad = norm[:, 0] < 1e-8
    if bad.any():
        blended[bad] = soft[bad]
        norm[bad] = np.linalg.norm(soft[bad], axis=1, keepdims=True)
    return blended / (norm + 1e-12)


def tangent_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two orthonormal vectors spanning the tangent plane perpendicular to normal."""
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    t1 = np.cross(n, ref)
    t1 = t1 / np.linalg.norm(t1)
    t2 = np.cross(n, t1)
    return t1, t2


def project_onto_normal(
    point: np.ndarray, anchor: np.ndarray, normal: np.ndarray
) -> np.ndarray:
    """Clamp a freely-dragged point back onto the line through anchor along normal.

    This is the "displace" constraint: motion only in/out along the normal.
    """
    point = np.asarray(point, dtype=np.float64)
    anchor = np.asarray(anchor, dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    normal = normal / np.linalg.norm(normal)
    return anchor + normal * float(np.dot(point - anchor, normal))


def project_onto_plane(
    point: np.ndarray, anchor: np.ndarray, normal: np.ndarray
) -> np.ndarray:
    """Clamp a freely-dragged point onto the tangent plane through anchor.

    This is the "slide along the surface" constraint: motion only in the plane
    perpendicular to the normal (no in/out displacement).
    """
    point = np.asarray(point, dtype=np.float64)
    anchor = np.asarray(anchor, dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    normal = normal / np.linalg.norm(normal)
    return point - normal * float(np.dot(point - anchor, normal))
