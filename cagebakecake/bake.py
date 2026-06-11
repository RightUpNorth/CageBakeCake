"""Headless tangent-space normal-map bake (no plotting).

The cage's whole purpose is realized here: per low-poly surface point it gives the
outer limit of a ray fired at the high poly, so the baker captures the intended
surface and not something behind it. The result is a tangent-space normal map: the
high-poly normal at each hit, expressed in the low poly's per-texel tangent frame, so
the map stays valid as the low poly deforms or is instanced.

Pure NumPy + trimesh so it runs and is tested without a window (see docs/baking.md).
The GUI Bake button (app.py) is a thin trigger over `bake`.

Inputs are explicit arrays, not meshes, to keep this format- and GUI-blind:

- low poly:  points (V,3), triangles (F,3), per-vertex normals (V,3),
             per-corner UVs (F,3,2)  -- faceVarying, the natural rasterization input
- cage:      points (V,3)            -- topology-matched to the low poly; the
                                        per-vertex outer ray limit
- high poly: points (H,3), triangles (G,3), per-vertex normals (H,3)

The low/cage/high are assumed to occupy the same world space (aligned and same scale),
as the baking algorithm requires; the GUI wiring that adapts pyvista.PolyData (USD
faceVarying `st`, quad triangulation) into these arrays is Phase 7.4.
"""

from __future__ import annotations

import numpy as np

FLAT_RGB = np.array([128, 128, 255], dtype=np.uint8)  # tangent-space (0,0,1)


# --- rasterization (Phase 7.1) ---------------------------------------------
def _rasterize_uv_triangles(
    uvs: np.ndarray, width: int, height: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Walk the UV triangles and record, per covered texel, which triangle covers it
    and the barycentric weights of the texel center within that triangle.

    UV (0,0) is bottom-left; image row 0 is the top, so v is flipped into row space.
    The grid is `height` rows by `width` columns (a non-square map is allowed). Later
    triangles overwrite earlier ones on overlap (last-writer-wins); UV layouts are not
    expected to overlap. Returns (texel_yx, tri_index, bary) for covered texels, where
    bary is (M,3) weights over the triangle's three corners.
    """
    w = int(width)
    h = int(height)
    tri_of = np.full((h, w), -1, dtype=np.int64)
    bary_of = np.zeros((h, w, 3), dtype=np.float64)

    # UV -> continuous pixel coords (x right, y down).
    px = uvs[..., 0] * w
    py = (1.0 - uvs[..., 1]) * h

    for f in range(uvs.shape[0]):
        x0, x1, x2 = px[f]
        y0, y1, y2 = py[f]
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(det) < 1e-12:  # degenerate UV triangle
            continue
        xmin = max(int(np.floor(min(x0, x1, x2))), 0)
        xmax = min(int(np.ceil(max(x0, x1, x2))), w - 1)
        ymin = max(int(np.floor(min(y0, y1, y2))), 0)
        ymax = min(int(np.ceil(max(y0, y1, y2))), h - 1)
        if xmin > xmax or ymin > ymax:
            continue

        ys, xs = np.mgrid[ymin : ymax + 1, xmin : xmax + 1]
        cx = xs + 0.5
        cy = ys + 0.5
        w0 = ((y1 - y2) * (cx - x2) + (x2 - x1) * (cy - y2)) / det
        w1 = ((y2 - y0) * (cx - x2) + (x0 - x2) * (cy - y2)) / det
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        ry = ys[inside]
        rx = xs[inside]
        tri_of[ry, rx] = f
        bary_of[ry, rx, 0] = w0[inside]
        bary_of[ry, rx, 1] = w1[inside]
        bary_of[ry, rx, 2] = w2[inside]

    yx = np.argwhere(tri_of >= 0)
    tri_index = tri_of[yx[:, 0], yx[:, 1]]
    bary = bary_of[yx[:, 0], yx[:, 1]]
    return yx, tri_index, bary


def _per_triangle_tangent(
    tri_pos: np.ndarray, tri_uv: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Tangent and bitangent per triangle from the UV gradient of its positions.

    tri_pos: (F,3,3) corner positions, tri_uv: (F,3,2) corner UVs. The tangent points
    along +U, the bitangent along +V; they are orthonormalized against the per-texel
    normal at encode time.
    """
    e1 = tri_pos[:, 1] - tri_pos[:, 0]
    e2 = tri_pos[:, 2] - tri_pos[:, 0]
    du1 = tri_uv[:, 1] - tri_uv[:, 0]
    du2 = tri_uv[:, 2] - tri_uv[:, 0]
    denom = du1[:, 0] * du2[:, 1] - du2[:, 0] * du1[:, 1]
    safe = np.abs(denom) > 1e-12  # degenerate UV triangles -> zero tangent (no warn)
    r = np.zeros_like(denom)
    r[safe] = 1.0 / denom[safe]
    r = r[:, None]
    tangent = (e1 * du2[:, 1, None] - e2 * du1[:, 1, None]) * r
    bitangent = (e2 * du1[:, 0, None] - e1 * du2[:, 0, None]) * r
    return tangent, bitangent


# --- tangent-space encode (Phase 7.3) --------------------------------------
def _encode_tangent_space(
    world_normals: np.ndarray, tbn_t: np.ndarray, tbn_b: np.ndarray, tbn_n: np.ndarray
) -> np.ndarray:
    """Project world-space hit normals into each texel's tangent frame and encode to
    RGB. The frame is orthonormalized (Gram-Schmidt T against N, B = N x T) so it is a
    proper rotation regardless of UV shear; a normal equal to N encodes to (128,128,255).
    """
    n = tbn_n / (np.linalg.norm(tbn_n, axis=1, keepdims=True) + 1e-12)
    t = tbn_t - n * np.sum(tbn_t * n, axis=1, keepdims=True)
    t = t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-12)
    b = np.cross(n, t)

    local = np.stack(
        [
            np.sum(world_normals * t, axis=1),
            np.sum(world_normals * b, axis=1),
            np.sum(world_normals * n, axis=1),
        ],
        axis=1,
    )
    local = local / (np.linalg.norm(local, axis=1, keepdims=True) + 1e-12)
    return np.clip((local * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)


# --- the bake (Phases 7.1-7.3) ---------------------------------------------
def bake(
    low_points: np.ndarray,
    low_tris: np.ndarray,
    low_normals: np.ndarray,
    low_uvs: np.ndarray,
    cage_points: np.ndarray,
    high_points: np.ndarray,
    high_tris: np.ndarray,
    high_normals: np.ndarray,
    resolution: "int | tuple[int, int]" = 1024,
    out_path: str | None = None,
    progress=None,
    firing_normals: np.ndarray | None = None,
) -> np.ndarray:
    """Bake a tangent-space normal map; return the (H,W,3) uint8 buffer.

    `resolution` is the map size: an int for a square map, or a (width, height) pair
    for a non-square one.

    `low_normals` is the low poly's shading normal - the frame the high-poly normal is
    encoded into (the normal the engine interpolates), and it must be the hard normals
    that author the map. `firing_normals` is the direction rays are cast along; pass the
    skew-blended normals here to bend the firing without moving cage points (M8.2). It
    defaults to `low_normals`, so a plain bake fires along the shading normal.

    For each covered texel: interpolate the low-poly surface point, normal, and cage
    point; fire a ray from the cage point inward along -normal through the surface and
    an equal distance beyond (the cage offset bounds it both ways); take the nearest
    high-poly hit; read its barycentric-interpolated world normal; encode into the
    texel's tangent frame. Missed texels stay flat (128,128,255).

    Writes a PNG when out_path is given. Raises ValueError if the low poly has no UVs.
    """
    low_uvs = np.asarray(low_uvs, dtype=np.float64)
    if low_uvs.size == 0 or low_uvs.shape != (low_tris.shape[0], 3, 2):
        raise ValueError(
            "low poly has no usable UVs: bake needs per-corner UVs shaped (F,3,2); "
            "got "
            f"{None if low_uvs.size == 0 else low_uvs.shape} for {low_tris.shape[0]} "
            "triangles (the low poly must carry a UV layout - see docs/baking.md)"
        )

    notify = progress or (lambda _msg: None)
    if isinstance(resolution, (tuple, list)):
        width, height = int(resolution[0]), int(resolution[1])
    else:
        width = height = int(resolution)
    notify(f"rasterizing {low_tris.shape[0]} triangles into {width}x{height}")
    yx, tri_index, bary = _rasterize_uv_triangles(low_uvs, width, height)
    image = np.tile(FLAT_RGB, (height, width, 1))
    if tri_index.size == 0:
        if out_path:
            _write_png(out_path, image)
        return image

    # Interpolate per-texel surface point, normals, and cage point. The shading normal
    # is the encode frame; the firing normal (skew-blended, M8.2) aims the rays.
    firing = low_normals if firing_normals is None else firing_normals
    corners = low_tris[tri_index]  # (M,3) vertex indices
    cpos = low_points[corners]  # (M,3,3)
    cnrm = low_normals[corners]
    cfire = firing[corners]
    ccage = cage_points[corners]
    w = bary[:, :, None]
    surf = np.sum(cpos * w, axis=1)
    shade = np.sum(cnrm * w, axis=1)
    shade = shade / (np.linalg.norm(shade, axis=1, keepdims=True) + 1e-12)
    direction = np.sum(cfire * w, axis=1)
    direction = direction / (np.linalg.norm(direction, axis=1, keepdims=True) + 1e-12)
    cage = np.sum(ccage * w, axis=1)

    offset = np.linalg.norm(cage - surf, axis=1)  # cage envelope thickness per texel
    eps = float(offset.max()) * 1e-4 + 1e-9
    origins = surf + direction * (offset[:, None] + eps)  # start at the cage, outside
    max_len = 2.0 * offset + 2.0 * eps  # sweep through the surface and equally inside

    notify(f"casting {len(origins)} rays into {high_tris.shape[0]} high-poly triangles")
    hit_normals, hit_mask = _cast_to_high(
        origins, -direction, max_len, high_points, high_tris, high_normals
    )

    # Per-triangle tangent basis, expanded to the covered texels. The frame normal is the
    # shading normal (not the firing direction), so skew does not distort the encoded map.
    tri_pos = low_points[low_tris]  # (F,3,3)
    tan, bit = _per_triangle_tangent(tri_pos, low_uvs)
    rgb = _encode_tangent_space(
        hit_normals[hit_mask],
        tan[tri_index][hit_mask],
        bit[tri_index][hit_mask],
        shade[hit_mask],
    )
    hit_yx = yx[hit_mask]
    image[hit_yx[:, 0], hit_yx[:, 1]] = rgb
    notify(f"{int(hit_mask.sum())}/{len(yx)} texels hit")

    if out_path:
        _write_png(out_path, image)
        notify(f"wrote {out_path}")
    return image


# --- cage-bounded ray casting (Phase 7.2) ----------------------------------
def _cast_to_high(
    origins: np.ndarray,
    dirs: np.ndarray,
    max_len: np.ndarray,
    high_points: np.ndarray,
    high_tris: np.ndarray,
    high_normals: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest high-poly hit per ray, with the barycentric-interpolated world normal.

    Returns (normals (M,3), mask (M,)) where mask is True for rays that hit within
    their length bound. Uses trimesh's embree backend when available.
    """
    import trimesh

    mesh = trimesh.Trimesh(
        vertices=np.asarray(high_points, dtype=np.float64),
        faces=np.asarray(high_tris, dtype=np.int64),
        process=False,
    )
    locations, ray_idx, tri_idx = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=dirs, multiple_hits=False
    )

    out = np.zeros((origins.shape[0], 3), dtype=np.float64)
    mask = np.zeros(origins.shape[0], dtype=bool)
    if len(ray_idx) == 0:
        return out, mask

    # Keep only hits within the per-ray cage bound (intersects_location is unbounded).
    dist = np.linalg.norm(locations - origins[ray_idx], axis=1)
    keep = dist <= max_len[ray_idx]
    ray_idx, tri_idx, locations = ray_idx[keep], tri_idx[keep], locations[keep]
    if len(ray_idx) == 0:
        return out, mask

    # Barycentric interpolation of high-poly vertex normals at each hit.
    tris = high_tris[tri_idx]
    p0, p1, p2 = (high_points[tris[:, 0]], high_points[tris[:, 1]], high_points[tris[:, 2]])
    bary = _barycentric(locations, p0, p1, p2)
    nrm = (
        high_normals[tris[:, 0]] * bary[:, 0, None]
        + high_normals[tris[:, 1]] * bary[:, 1, None]
        + high_normals[tris[:, 2]] * bary[:, 2, None]
    )
    out[ray_idx] = nrm
    mask[ray_idx] = True
    return out, mask


def _barycentric(p, a, b, c) -> np.ndarray:
    """Barycentric coordinates of points p within triangles (a,b,c), vectorized."""
    v0 = b - a
    v1 = c - a
    v2 = p - a
    d00 = np.sum(v0 * v0, axis=1)
    d01 = np.sum(v0 * v1, axis=1)
    d11 = np.sum(v1 * v1, axis=1)
    d20 = np.sum(v2 * v0, axis=1)
    d21 = np.sum(v2 * v1, axis=1)
    denom = d00 * d11 - d01 * d01
    denom = np.where(np.abs(denom) < 1e-12, 1.0, denom)
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w
    return np.stack([u, v, w], axis=1)


def _write_png(path: str, image: np.ndarray) -> None:
    import imageio.v3 as iio

    iio.imwrite(path, image)
