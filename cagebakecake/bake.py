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
# found the high poly, and where it missed it is split into too-tight poke-through
# (orange: the high poly pokes out *beyond* the cage) and too-loose / no-surface (red:
# no high poly nearby in either direction). Uncovered background is dark grey; a
# partly-covered texel blends these by the fraction of its subtexels in each class.
MISS_HIT = np.array([40, 160, 40], dtype=np.uint8)
MISS_POKE = np.array([235, 140, 30], dtype=np.uint8)   # too tight (poke-through)
MISS_MISS = np.array([230, 50, 50], dtype=np.uint8)    # too loose / no surface
MISS_BG = np.array([28, 28, 30], dtype=np.uint8)


# --- rasterization (Phase 7.1) ---------------------------------------------
def _rasterize_uv_triangles(
    uvs: np.ndarray, width: int, height: int, faces=None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Walk the UV triangles and record, per covered texel, which triangle covers it
    and the barycentric weights of the texel center within that triangle.

    UV (0,0) is bottom-left; image row 0 is the top, so v is flipped into row space.
    The grid is `height` rows by `width` columns (a non-square map is allowed). Later
    triangles overwrite earlier ones on overlap (last-writer-wins); UV layouts are not
    expected to overlap. Returns (texel_yx, tri_index, bary) for covered texels, where
    bary is (M,3) weights over the triangle's three corners.

    `faces` optionally restricts rasterization to a subset of triangle indices (for an
    incremental re-bake of just the dirty faces); the returned tri_index still carries the
    global face id. Default rasterizes every triangle.
    """
    w = int(width)
    h = int(height)
    tri_of = np.full((h, w), -1, dtype=np.int64)
    bary_of = np.zeros((h, w, 3), dtype=np.float64)

    # UV -> continuous pixel coords (x right, y down).
    px = uvs[..., 0] * w
    py = (1.0 - uvs[..., 1]) * h

    face_iter = range(uvs.shape[0]) if faces is None else (int(i) for i in faces)
    for f in face_iter:
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


def _encode_object_space(world_normals: np.ndarray) -> np.ndarray:
    """Encode world/object-space hit normals straight to RGB ((n*0.5+0.5)*255), with no
    tangent transform. An object-space normal map: valid only while the mesh keeps its
    baked orientation, but free of tangent-basis mismatch."""
    n = world_normals / (np.linalg.norm(world_normals, axis=1, keepdims=True) + 1e-12)
    return np.clip((n * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)


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
    return_face_miss: bool = False,
    space: str = "tangent",
    ray_mesh=None,
) -> "np.ndarray | tuple | None":
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

    `space` selects the encoding: "tangent" (the default tangent-space map) or "object"
    (the world-space hit normal encoded directly, no tangent transform).

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
    is a ray-miss / projection-feedback image at the output resolution showing where the
    cage failed to capture the high poly - green where a ray hit it, orange where the high
    poly pokes out beyond the cage (too tight), red where nothing was found nearby (too
    loose), dark background. With `return_face_miss`, also returns a per-low-face class
    array (`(image, miss_map, face_class)`; 0 ok, 1 poke-through, 2 loose) for a 3D
    in-viewport overlay. Cancelled bakes still return None.
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
            miss = np.tile(MISS_BG, (height, width, 1))  # nothing covered
            if return_face_miss:
                return image, miss, np.zeros(low_tris.shape[0], dtype=np.int64)
            return image, miss
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
    cast_mesh = ray_mesh if ray_mesh is not None else make_ray_mesh(high_points, high_tris)
    hit_normals, hit_mask = _cast_to_high(
        origins, -direction, max_len, high_points, high_tris, high_normals, ray_mesh=cast_mesh
    )

    # Per-triangle tangent basis, expanded to the covered texels. The frame normal is the
    # shading normal (not the firing direction), so skew does not distort the encoded map.
    # Object space skips the tangent transform and encodes the world normal directly.
    if space == "object":
        rgb = _encode_object_space(hit_normals[hit_mask])
    else:
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
        # Classify the missed texels: cast outward (past the cage) from the cage point;
        # a hit means the high poly pokes out beyond the cage (too tight = poke-through),
        # otherwise the cage is too loose / there is no surface nearby.
        poke = np.zeros(len(yx), dtype=bool)
        miss_idx = np.nonzero(~hit_mask)[0]
        if len(miss_idx):
            _n, out_hit = _cast_to_high(
                origins[miss_idx], direction[miss_idx], offset[miss_idx] + eps,
                high_points, high_tris, high_normals, ray_mesh=cast_mesh)
            poke[miss_idx] = out_hit
        miss = _miss_map(yx, hit_mask, covered, ss, width, height, poke=poke)
        if return_face_miss:
            return image, miss, _face_miss_class(
                low_tris.shape[0], tri_index, hit_mask, poke)
        return image, miss
    return image


# --- incremental re-bake (additive) ----------------------------------------
def rebake_faces(
    prev_image: np.ndarray,
    low_points: np.ndarray,
    low_tris: np.ndarray,
    low_normals: np.ndarray,
    low_uvs: np.ndarray,
    cage_points: np.ndarray,
    high_points: np.ndarray,
    high_tris: np.ndarray,
    high_normals: np.ndarray,
    faces,
    resolution: "int | tuple[int, int]" = 1024,
    firing_normals: np.ndarray | None = None,
    ray_mesh=None,
    progress=None,
) -> np.ndarray:
    """Re-bake only `faces` (indices into low_tris) and composite over a copy of
    `prev_image`, returning the new (H,W,3) buffer.

    This is the additive / incremental re-bake: a cage edit that only touched a small
    region maps to a few dirty faces, so re-casting just their texels and pasting the
    result over the last full bake is far cheaper than a whole-map re-bake. Covered texels
    whose ray now misses reset to FLAT_RGB (the region may have stopped reaching the
    surface). Supersample and island padding are not applied - it is an interactive update
    over a prior full bake, which already carries them. The per-texel cast mirrors `bake`.
    """
    low_uvs = np.asarray(low_uvs, dtype=np.float64)
    if isinstance(resolution, (tuple, list)):
        width, height = int(resolution[0]), int(resolution[1])
    else:
        width = height = int(resolution)
    notify = progress or (lambda _msg: None)
    yx, tri_index, bary = _rasterize_uv_triangles(low_uvs, width, height, faces=faces)
    image = np.array(prev_image, dtype=np.uint8, copy=True)
    if tri_index.size == 0:
        return image

    firing = low_normals if firing_normals is None else firing_normals
    corners = low_tris[tri_index]
    w = bary[:, :, None]
    surf = np.sum(low_points[corners] * w, axis=1)
    shade = np.sum(low_normals[corners] * w, axis=1)
    shade = shade / (np.linalg.norm(shade, axis=1, keepdims=True) + 1e-12)
    direction = np.sum(firing[corners] * w, axis=1)
    direction = direction / (np.linalg.norm(direction, axis=1, keepdims=True) + 1e-12)
    cage = np.sum(cage_points[corners] * w, axis=1)

    offset = np.linalg.norm(cage - surf, axis=1)
    eps = float(offset.max()) * 1e-4 + 1e-9
    origins = surf + direction * (offset[:, None] + eps)
    max_len = 2.0 * offset + 2.0 * eps
    hit_normals, hit_mask = _cast_to_high(
        origins, -direction, max_len, high_points, high_tris, high_normals, ray_mesh=ray_mesh)

    tan, bit = _per_triangle_tangent(low_points[low_tris], low_uvs)
    rgb = _encode_tangent_space(
        hit_normals[hit_mask], tan[tri_index][hit_mask], bit[tri_index][hit_mask],
        shade[hit_mask])
    image[yx[:, 0], yx[:, 1]] = FLAT_RGB     # reset the dirty region, then paint hits
    hit_yx = yx[hit_mask]
    image[hit_yx[:, 0], hit_yx[:, 1]] = rgb
    notify(f"re-baked {len(faces)} faces, {int(hit_mask.sum())}/{len(yx)} texels hit")
    return image


# --- ray-miss / projection feedback ----------------------------------------
def _miss_map(yx, hit_mask, covered, ss: int, width: int, height: int,
              poke=None) -> np.ndarray:
    """An (H,W,3) projection-feedback image: per output texel, a blend of green (covered
    subtexels whose ray hit the high poly), orange (missed but the high poly pokes out
    beyond the cage = too tight) and red (missed with nothing nearby = too loose), over a
    dark background where nothing was covered. `covered`/`hit`/`poke` live at render
    (supersampled) resolution; subtexels are averaged down into (height, width) blocks.

    `poke` (per covered texel, aligned with `yx`) splits the misses; when None every miss
    is treated as too-loose (the old green/red behaviour)."""
    rh, rw = covered.shape
    hits = np.zeros((rh, rw), dtype=bool)
    hits[yx[hit_mask][:, 0], yx[hit_mask][:, 1]] = True
    poke_grid = np.zeros((rh, rw), dtype=bool)
    if poke is not None and poke.any():
        py = yx[poke]
        poke_grid[py[:, 0], py[:, 1]] = True
    hit_cov = hits & covered
    poke_cov = poke_grid & covered & ~hits
    loose_cov = covered & ~hits & ~poke_grid

    def blocks(mask):
        return mask.reshape(height, ss, width, ss).sum(axis=(1, 3)).astype(np.float64)

    cov_b = blocks(covered)
    out = np.tile(MISS_BG, (height, width, 1))
    has = cov_b > 0
    col = (MISS_HIT.astype(np.float64)[None, None] * blocks(hit_cov)[..., None]
           + MISS_POKE.astype(np.float64)[None, None] * blocks(poke_cov)[..., None]
           + MISS_MISS.astype(np.float64)[None, None] * blocks(loose_cov)[..., None])
    col[has] /= cov_b[has][:, None]
    out[has] = np.clip(col[has], 0, 255).astype(np.uint8)
    return out


def _face_miss_class(num_faces: int, tri_index, hit_mask, poke) -> np.ndarray:
    """Per low-poly face miss class for the 3D overlay: 0 ok (no missed texel), 2 too
    loose, 1 poke-through (too tight). Poke takes priority, so a face that pokes anywhere
    shows as too-tight even if it also has loose misses."""
    cls = np.zeros(num_faces, dtype=np.int64)
    miss = ~hit_mask
    loose = miss & ~poke
    cls[np.unique(tri_index[loose])] = 2
    cls[np.unique(tri_index[miss & poke])] = 1  # poke overrides loose
    return cls


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
    ray_mesh=None,
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

    mesh = ray_mesh if ray_mesh is not None else make_ray_mesh(high_points, high_tris)
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


def flip_green(image: np.ndarray) -> np.ndarray:
    """Invert the green channel of a normal map (G -> 255-G): converts between OpenGL
    (+Y up) and DirectX (-Y down) tangent-space conventions. Returns a new array."""
    out = np.array(image, dtype=np.uint8, copy=True)
    out[..., 1] = 255 - out[..., 1]
    return out


def pack_outputs(baked: dict, recipe, lp_name: str) -> dict:
    """Compose a recipe's output files from already-baked maps.

    `baked` maps a BakeMap id -> its (H,W,3) uint8 buffer (only maps that were
    actually baked appear). For each output in `recipe`, assemble an (H,W,4) uint8
    RGBA image by reading the assigned source per channel, and key it by its
    resolved filename (`{LP}` expanded, `.png` appended). A `color` output takes its
    RGB from the single source in channel r and its alpha from channel a; a `packed`
    output takes each of R/G/B/A from its own single-channel source. Unassigned (or
    not-yet-bakeable) sources leave that channel at its default: 0 for RGB, 255 for
    alpha (opaque). Returns {} if nothing was baked (no reference resolution).
    """
    ref = next(iter(baked.values()), None)
    if ref is None:
        return {}
    height, width = ref.shape[:2]

    def gray(map_id):
        arr = baked.get(map_id)
        return None if arr is None else arr[..., 0]

    result: dict[str, np.ndarray] = {}
    for out in recipe.outputs:
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., 3] = 255  # opaque unless an alpha source is assigned
        if out.type == "color":
            src = baked.get(out.ch.get("r"))
            if src is not None:
                rgba[..., :3] = src[..., :3]
            a = gray(out.ch.get("a"))
            if a is not None:
                rgba[..., 3] = a
        else:  # packed: each channel its own single-channel source
            for i, c in enumerate(("r", "g", "b")):
                g = gray(out.ch.get(c))
                if g is not None:
                    rgba[..., i] = g
            a = gray(out.ch.get("a"))
            if a is not None:
                rgba[..., 3] = a
        filename = f"{out.file.replace('{LP}', lp_name)}.png"
        result[filename] = rgba
    return result


# --- exploded bake (per-part separation) -----------------------------------
def explode_translation(points: np.ndarray, ranges, center, factor: float) -> np.ndarray:
    """Per-point translation that pushes each part radially away from `center` by
    factor * (part centroid - center). `ranges` is a list of (name, start, count) point
    spans into `points`. Returns an (N,3) offset to add to `points`.

    Used for an exploded bake: separating the parts so a cage's rays no longer cross from
    one part into a neighbour. A matched low/high pair shares a centroid, so both move by
    the same offset and stay aligned for the bake, while distinct parts diverge.
    """
    pts = np.asarray(points, dtype=np.float64)
    c = np.asarray(center, dtype=np.float64)
    out = np.zeros_like(pts)
    for _name, start, count in ranges:
        if count <= 0:
            continue
        centroid = pts[start:start + count].mean(axis=0)
        out[start:start + count] = (centroid - c) * float(factor)
    return out


# --- cage-bounded ray casting (Phase 7.2) ----------------------------------
def make_ray_mesh(high_points: np.ndarray, high_tris: np.ndarray):
    """A trimesh whose embree BVH is built once (on first ray query) and cached on it.

    Building the BVH over a dense high poly is the dominant bake cost (~9 s for 13M
    triangles), and it does not change while the cage is edited. Build this once and
    pass it to `bake` / `bake_ao` as `ray_mesh` so repeat bakes skip the rebuild; make a
    fresh one only when the high poly itself changes.
    """
    import trimesh

    return trimesh.Trimesh(
        vertices=np.asarray(high_points, dtype=np.float64),
        faces=np.asarray(high_tris, dtype=np.int64),
        process=False,
    )


def _cast_to_high(
    origins: np.ndarray,
    dirs: np.ndarray,
    max_len: np.ndarray,
    high_points: np.ndarray,
    high_tris: np.ndarray,
    high_normals: np.ndarray,
    ray_mesh=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest high-poly hit per ray, with the barycentric-interpolated world normal.

    Returns (normals (M,3), mask (M,)) where mask is True for rays that hit within
    their length bound. Uses trimesh's embree backend when available. Pass `ray_mesh`
    (from `make_ray_mesh`) to reuse a cached BVH across bakes; otherwise one is built.
    """
    mesh = ray_mesh if ray_mesh is not None else make_ray_mesh(high_points, high_tris)
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
