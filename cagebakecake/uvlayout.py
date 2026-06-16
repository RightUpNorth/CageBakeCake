"""UV layout rendering for the 2D pane.

Draws the low poly's UV islands so the artist can see seams, wasted space, and (when a
bake is shown beneath) which islands are covered. Pure NumPy producing an (H,W,3) uint8
image - the same buffer kind ImageView consumes - so it has no Qt or VTK dependency and
is unit-tested headlessly.

Either over a checkerboard (no bake yet) or over a baked map (the bake is already in UV
space, so this overlays the island wireframe on the texture = a UV-space texture view).
"""

from __future__ import annotations

import numpy as np

EDGE = np.array([30, 30, 36], dtype=np.uint8)        # UV island wireframe colour
CHECK_A = np.array([207, 207, 207], dtype=np.uint8)  # checker light
CHECK_B = np.array([188, 188, 188], dtype=np.uint8)  # checker dark


def _checker(height: int, width: int, size: int = 16) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    dark = ((xx // size + yy // size) % 2).astype(bool)
    img = np.empty((height, width, 3), dtype=np.uint8)
    img[~dark] = CHECK_A
    img[dark] = CHECK_B
    return img


def _line_points(x0, y0, x1, y1):
    """Pixel coordinates along each segment (x0,y0)->(x1,y1), vectorized over all
    segments. Each segment is sampled at max(|dx|,|dy|)+1 points (so it is gap-free);
    returns flat (xs, ys) integer arrays of every sampled pixel."""
    n = np.maximum(np.abs(x1 - x0), np.abs(y1 - y0)).astype(np.int64) + 1
    total = int(n.sum())
    if total == 0:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    edge = np.repeat(np.arange(len(n)), n)            # which segment each sample belongs to
    start = np.zeros(len(n), np.int64)
    start[1:] = np.cumsum(n)[:-1]
    j = np.arange(total) - start[edge]                # step index within the segment
    t = j / np.maximum(n[edge] - 1, 1)
    xs = np.round(x0[edge] + (x1[edge] - x0[edge]) * t).astype(np.int64)
    ys = np.round(y0[edge] + (y1[edge] - y0[edge]) * t).astype(np.int64)
    return xs, ys


def layout_image(uvs: np.ndarray, width: int = 1024, height: int = 1024,
                 base: np.ndarray | None = None, edge_color=EDGE) -> np.ndarray:
    """Render the UV islands as an (H,W,3) uint8 image: the triangle edges (seams /
    island outlines) drawn over `base` if given (a baked map, already in UV space), else
    over a checkerboard at (height, width). `uvs` is per-corner (F,3,2)."""
    if base is not None:
        img = np.ascontiguousarray(np.asarray(base)[..., :3].astype(np.uint8)).copy()
        height, width = img.shape[:2]
    else:
        img = _checker(height, width)

    uvs = np.asarray(uvs, dtype=np.float64)
    if uvs.size == 0:
        return img
    ax = np.clip(uvs[:, :, 0] * width, 0, width - 1)
    ay = np.clip((1.0 - uvs[:, :, 1]) * height, 0, height - 1)
    # The three edges of every triangle: corner k -> corner (k+1) mod 3.
    x0 = ax[:, [0, 1, 2]].ravel()
    y0 = ay[:, [0, 1, 2]].ravel()
    x1 = ax[:, [1, 2, 0]].ravel()
    y1 = ay[:, [1, 2, 0]].ravel()
    xs, ys = _line_points(x0, y0, x1, y1)
    img[ys, xs] = np.asarray(edge_color, dtype=np.uint8)
    return img
