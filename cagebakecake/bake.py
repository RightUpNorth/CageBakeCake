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

# Ray-miss / projection-feedback map colours: a covered texel is green where its ray
# found the high poly and red where it missed (the cage failed to reach a surface);
# uncovered background is dark grey. Partly-covered texels lerp green->red by miss frac.
MISS_HIT = np.array([40, 160, 40], dtype=np.uint8)
MISS_MISS = np.array([230, 50, 50], dtype=np.uint8)
MISS_BG = np.array([28, 28, 30], dtype=np.uint8)


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
    supersample: int = 1,
    padding: int = 0,
    should_cancel=None,
    return_miss: bool = False,
) -> "np.ndarray | tuple[np.ndarray, np.ndarray] | None":
    """Bake a tangent-space normal map; return the (H,W,3) uint8 buffer.

    `should_cancel` is an optional predicate polled before the expensive ray cast; if it
    returns true the bake aborts and returns None.

    `resolution` is the map size: an int for a square map, or a (width, height) pair
    for a non-square one.

    `supersample` >= 1 bakes at that multiple of the size and box-averages the
    tangent-space normals (renormalized) down to the target, to anti-alias edges.
    `padding` >= 0 bleeds the baked colours that many texels past the UV-island edges
    into the background, so mip-mapping does not pull the flat background across seams
    (use a large value to flood-fill the whole background).

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

    With `return_miss`, returns `(image, miss_map)` instead of just `image`: the miss map
    is a ray-miss / projection-feedback image (green where a ray hit the high poly, red
    where it missed, dark background) at the output resolution - it shows where the cage
    failed to reach a surface. Cancelled bakes still return None.
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
    ss = max(1, int(supersample))
    rw, rh = width * ss, height * ss  # render (possibly supersampled) resolution
    msg = f"{rw}x{rh}" + (f" (->{width}x{height} x{ss})" if ss > 1 else "")
    notify(f"rasterizing {low_tris.shape[0]} triangles into {msg}")
    yx, tri_index, bary = _rasterize_uv_triangles(low_uvs, rw, rh)
    image = np.tile(FLAT_RGB, (rh, rw, 1))
    covered = np.zeros((rh, rw), dtype=bool)  # texels inside a UV island (for padding)
    if tri_index.size == 0:
        image = _downsample(image, covered, ss, width, height)[0]
        if out_path:
            _write_png(out_path, image)
        if return_miss:
            return image, np.tile(MISS_BG, (height, width, 1))  # nothing covered
        return image
    covered[yx[:, 0], yx[:, 1]] = True

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

    if should_cancel and should_cancel():
        notify("cancelled")
        return None
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

    image, mask = _downsample(image, covered, ss, width, height)
    if padding > 0:
        image = _pad_islands(image, mask, int(padding))
        notify(f"padded {int(padding)} texels past island edges")
    if out_path:
        _write_png(out_path, image)
        notify(f"wrote {out_path}")
    if return_miss:
        miss = _miss_map(yx, hit_mask, covered, ss, width, height)
        return image, miss
    return image


# --- ray-miss / projection feedback ----------------------------------------
def _miss_map(yx, hit_mask, covered, ss: int, width: int, height: int) -> np.ndarray:
    """An (H,W,3) projection-feedback image: per output texel, green where every covered
    subtexel's ray hit the high poly, red where they all missed, lerped between for a
    partial block, and dark background where nothing was covered. `covered`/`hit` live at
    render (supersampled) resolution; blocks are averaged down to (height, width)."""
    rh, rw = covered.shape
    hits = np.zeros((rh, rw), dtype=bool)
    hy = yx[hit_mask]
    hits[hy[:, 0], hy[:, 1]] = True
    miss = covered & ~hits
    cov_blocks = covered.reshape(height, ss, width, ss).sum(axis=(1, 3)).astype(np.float64)
    miss_blocks = miss.reshape(height, ss, width, ss).sum(axis=(1, 3)).astype(np.float64)
    out = np.tile(MISS_BG, (height, width, 1))
    has = cov_blocks > 0
    frac = np.zeros((height, width), dtype=np.float64)
    frac[has] = miss_blocks[has] / cov_blocks[has]
    col = (MISS_HIT.astype(np.float64)[None, None] * (1.0 - frac[..., None])
           + MISS_MISS.astype(np.float64)[None, None] * frac[..., None])
    out[has] = np.clip(col[has], 0, 255).astype(np.uint8)
    return out


# --- supersample downsample + island padding (stretch: bake quality) --------
def _downsample(image: np.ndarray, covered: np.ndarray, ss: int, width: int, height: int):
    """Box-average an ss-supersampled buffer down to (height, width). Normals are
    averaged as vectors over each block's *covered* subtexels and renormalized; blocks
    with no coverage stay flat. Returns (image (H,W,3) uint8, covered (H,W) bool)."""
    if ss == 1:
        return image, covered
    n = image.reshape(height, ss, width, ss, 3).astype(np.float64) / 255.0 * 2.0 - 1.0
    c = covered.reshape(height, ss, width, ss).astype(np.float64)
    wsum = c.sum(axis=(1, 3))                       # (H,W) covered subtexels per block
    acc = (n * c[..., None]).sum(axis=(1, 3))       # (H,W,3) summed covered normals
    out = np.tile(FLAT_RGB, (height, width, 1))
    block_cov = wsum > 0
    vecs = acc[block_cov] / wsum[block_cov][:, None]
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)
    out[block_cov] = np.clip((vecs * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)
    return out, block_cov


def _pad_islands(image: np.ndarray, mask: np.ndarray, padding: int) -> np.ndarray:
    """Bleed filled (masked) colours into the background up to `padding` texels, using
    each empty texel's nearest filled texel (edge padding for mip safety)."""
    if not mask.any() or mask.all():
        return image
    from scipy import ndimage

    empty = ~mask
    dist, (iy, ix) = ndimage.distance_transform_edt(empty, return_indices=True)
    fill = empty & (dist <= padding)
    out = image.copy()
    out[fill] = image[iy[fill], ix[fill]]
    return out


# --- extra maps: ambient occlusion + curvature (stretch) -------------------
def _tangent_basis_array(normals: np.ndarray):
    """Per-row orthonormal (T, B) spanning the plane perpendicular to each normal."""
    ref = np.where(np.abs(normals[:, :1]) < 0.9, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    t = np.cross(normals, ref)
    t = t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-12)
    b = np.cross(normals, t)
    return t, b


def _hemisphere(n: int) -> np.ndarray:
    """`n` cosine-weighted directions over the +Z hemisphere (deterministic Fibonacci),
    so AO is reproducible. z is up (the surface normal)."""
    i = np.arange(n)
    r = np.sqrt((i + 0.5) / n)
    golden = np.pi * (3.0 - np.sqrt(5.0))
    theta = i * golden
    z = np.sqrt(np.clip(1.0 - r * r, 0.0, 1.0))
    return np.stack([r * np.cos(theta), r * np.sin(theta), z], axis=1)


def _gray_to_rgb(gray: np.ndarray) -> np.ndarray:
    """(H,W) float in [0,1] -> (H,W,3) uint8 grayscale (rounded, so 0.5 -> 128)."""
    g = np.clip(np.round(gray * 255.0), 0, 255).astype(np.uint8)
    return np.repeat(g[:, :, None], 3, axis=2)


def bake_ao(
    low_points, low_tris, low_normals, low_uvs,
    high_points, high_tris,
    resolution: "int | tuple[int, int]" = 1024,
    samples: int = 64,
    max_dist: float | None = None,
    out_path: str | None = None,
    progress=None,
    padding: int = 0,
    should_cancel=None,
) -> np.ndarray | None:
    """Bake an ambient-occlusion map of the high poly onto the low poly's UVs.

    `should_cancel` is polled before each hemisphere sample; if it returns true the bake
    aborts and returns None (the per-sample loop is what makes AO interruptible).

    Per covered texel: fire `samples` cosine-weighted rays over the hemisphere around the
    shading normal and measure the fraction blocked by the high poly within `max_dist`
    (default half the low-poly bbox diagonal). AO = 1 - occluded fraction; white is open,
    dark is occluded. Background stays white. `padding` bleeds past island edges.
    """
    low_uvs = np.asarray(low_uvs, dtype=np.float64)
    if low_uvs.size == 0 or low_uvs.shape != (low_tris.shape[0], 3, 2):
        raise ValueError("low poly has no usable UVs: bake_ao needs per-corner UVs (F,3,2)")
    notify = progress or (lambda _msg: None)
    width, height = (resolution, resolution) if isinstance(resolution, int) else (
        int(resolution[0]), int(resolution[1]))
    yx, tri_index, bary = _rasterize_uv_triangles(low_uvs, width, height)
    image = np.full((height, width, 3), 255, dtype=np.uint8)  # open = white
    if tri_index.size == 0:
        if out_path:
            _write_png(out_path, image)
        return image

    corners = low_tris[tri_index]
    w = bary[:, :, None]
    surf = np.sum(low_points[corners] * w, axis=1)
    nrm = np.sum(low_normals[corners] * w, axis=1)
    nrm = nrm / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12)
    tan, bit = _tangent_basis_array(nrm)

    if max_dist is None:
        max_dist = 0.5 * float(np.linalg.norm(np.ptp(low_points, axis=0)))
    eps = max_dist * 1e-3 + 1e-9
    origins = surf + nrm * eps

    import trimesh
    mesh = trimesh.Trimesh(vertices=np.asarray(high_points, dtype=np.float64),
                           faces=np.asarray(high_tris, dtype=np.int64), process=False)
    samples = int(samples)
    notify(f"AO: {samples} rays x {len(origins)} texels into {len(high_tris)} triangles")
    occ = np.zeros(len(origins))
    dirs_local = _hemisphere(samples)
    for s in range(samples):
        if should_cancel and should_cancel():
            notify("cancelled")
            return None
        lx, ly, lz = dirs_local[s]
        d = tan * lx + bit * ly + nrm * lz
        loc, ray_idx, _tri = mesh.ray.intersects_location(
            ray_origins=origins, ray_directions=d, multiple_hits=False)
        if len(ray_idx):
            dist = np.linalg.norm(loc - origins[ray_idx], axis=1)
            np.add.at(occ, ray_idx[dist <= max_dist], 1.0)
        notify(f"AO {s + 1}/{samples}")
    ao = 1.0 - occ / float(samples)

    gray = np.clip(ao * 255.0, 0, 255).astype(np.uint8)
    image[yx[:, 0], yx[:, 1]] = np.repeat(gray[:, None], 3, axis=1)  # per-texel grayscale
    notify("AO done")
    if padding > 0:
        mask = np.zeros((height, width), dtype=bool)
        mask[yx[:, 0], yx[:, 1]] = True
        image = _pad_islands(image, mask, int(padding))
    if out_path:
        _write_png(out_path, image)
        notify(f"wrote {out_path}")
    return image


def curvature_from_normal_map(normal_image: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Derive a curvature map from a tangent-space normal map (cheap 2D post-process).

    Curvature ~ the divergence of the tangent normal's xy across UV space: convex ridges
    go bright, concave cavities dark, flat stays neutral grey (128). Useful for masks.
    """
    from scipy import ndimage

    img = np.asarray(normal_image, dtype=np.float64)
    nx = img[..., 0] / 255.0 * 2.0 - 1.0
    ny = img[..., 1] / 255.0 * 2.0 - 1.0
    div = ndimage.sobel(nx, axis=1) + ndimage.sobel(ny, axis=0)
    gray = np.clip(0.5 + div * strength * 0.5, 0.0, 1.0)
    return _gray_to_rgb(gray)


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
