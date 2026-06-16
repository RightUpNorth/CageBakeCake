"""Headless batch / CLI baking - no window, no GL.

The GUI bakes through `CageEditor`, which builds a PyVista plotter and actors. For
automation (baking many asset pairs in a pipeline, or re-baking a saved project) that
GL dependency is dead weight, so this module bakes straight from the headless core:
`meshio` loads the meshes, `cage` builds the offset cage, and `bake` casts the rays.

Two entry points, both returning the written PNG paths:

- ``bake_pair`` - an ad-hoc bake of a low/high (+ optional cage) pair to per-type maps.
- ``bake_project`` - load a ``.cbcproj`` and bake its recipe with the saved cage edits and
  bake settings, packing the recipe's output PNGs.

Pure enough to unit-test without a display (tests author tiny UV'd USDs). See
docs/feature-gaps.md G (batch / CLI bake).
"""

from __future__ import annotations

import os

import numpy as np

from . import bake, cage, meshio, project, recipe as _recipe


def _load_cage_base(low_points, normals, cage_path):
    """Rest cage geometry: a topology-matched cage file used directly, an arbitrary cage
    resampled onto the low poly, or - with no cage file - a copy of the low poly."""
    if not cage_path:
        return np.asarray(low_points, dtype=np.float64).copy()
    cage_mesh = meshio.load_mesh(cage_path)
    if len(cage_mesh.points) == len(low_points):
        return np.asarray(cage_mesh.points, dtype=np.float64).copy()
    tris, _ = meshio.load_faces_uvs(cage_path, with_uvs=False)
    return cage.resample_cage(low_points, normals, cage_mesh.points, tris)


def _build_cage(low, cage_path, edits, push):
    """(hard_normals, firing_normals, cage_points) for the bake. `edits` is a decoded
    project edit dict (or None); `push` overrides the global offset when given."""
    hard = np.asarray(low.point_normals, dtype=np.float64)
    soft = cage.soft_vertex_normals(low.points, hard)
    n = len(hard)
    skew_map = np.full(n, 1.0)
    manual = np.zeros((n, 3))
    aim = np.zeros((n, 3))
    gp = push
    if edits:
        gp2, manual2, _skew, skew_map2, aim2, matched = project.decode_edits(edits, n)
        skew_map = skew_map2
        if matched:
            manual = manual2
            aim = aim2
        if push is None:
            gp = gp2
    # Firing normals = the skew blend tilted by the auto-solver's aim delta (matches
    # CageEditor._compose_normals so a baked project reproduces the interactive cage).
    blended = cage.blend_normals(hard, soft, skew_map)
    firing = blended + aim
    normals = firing / (np.linalg.norm(firing, axis=1, keepdims=True) + 1e-12)
    base = _load_cage_base(low.points, normals, cage_path)
    if gp is None:
        gp = float(np.linalg.norm(np.ptp(base, axis=0))) * 0.03
    return hard, normals, cage.compose(base, normals, float(gp), manual)


def _explode(low, high, low_ranges, high_ranges, cage_points, factor):
    """Apply an exploded-bake separation to (low, cage, high) points; returns the moved
    arrays. `factor` <= 0 leaves them unchanged."""
    lp, cp, hp = low.points, cage_points, high.points
    if factor <= 0.0:
        return lp, cp, hp
    lo = np.minimum(lp.min(axis=0), hp.min(axis=0))
    hi = np.maximum(lp.max(axis=0), hp.max(axis=0))
    center = 0.5 * (lo + hi)
    low_off = bake.explode_translation(lp, low_ranges, center, factor)
    high_off = bake.explode_translation(hp, high_ranges, center, factor)
    return lp + low_off, cp + low_off, hp + high_off


def _bake_maps(scene_low, scene_high, hard, normals, cage_points, kinds, *,
               size, supersample, padding, ao_samples, flip_green, explode, progress):
    """Bake the requested map kinds to memory; returns {kind: (H,W,3) image}. Shared by
    the ad-hoc and project bakes."""
    low, high = scene_low["merged"], scene_high["merged"]
    low_tris, low_uvs = scene_low["tris"], scene_low["uvs"]
    high_tris = scene_high["tris"]
    if low_uvs is None:
        raise ValueError("the low poly has no UVs; cannot bake")
    lp, cp, hp = _explode(low, high, scene_low["ranges"], scene_high["ranges"],
                          cage_points, explode)
    ray_mesh = bake.make_ray_mesh(hp, high_tris)
    high_normals = np.asarray(high.point_normals, dtype=np.float64)
    out: dict = {}
    if "normal" in kinds or "curv" in kinds:
        img = bake.bake(lp, low_tris, hard, low_uvs, cp, hp, high_tris, high_normals,
                        resolution=size, firing_normals=normals, supersample=supersample,
                        padding=padding, ray_mesh=ray_mesh, progress=progress)
        out["normal"] = bake.flip_green(img) if flip_green else img
    if "objnormal" in kinds:
        out["objnormal"] = bake.bake(
            lp, low_tris, hard, low_uvs, cp, hp, high_tris, high_normals, resolution=size,
            firing_normals=normals, supersample=supersample, padding=padding,
            space="object", ray_mesh=ray_mesh, progress=progress)
    if "ao" in kinds:
        out["ao"] = bake.bake_ao(lp, low_tris, hard, low_uvs, hp, high_tris,
                                 resolution=size, samples=ao_samples, padding=padding,
                                 ray_mesh=ray_mesh, progress=progress)
    if "height" in kinds:
        out["height"] = bake.bake_height(lp, low_tris, hard, low_uvs, cp, hp, high_tris,
                                         resolution=size, firing_normals=normals,
                                         padding=padding, ray_mesh=ray_mesh, progress=progress)
    if "position" in kinds:
        out["position"] = bake.bake_position(lp, low_tris, hard, low_uvs, cp, hp, high_tris,
                                             resolution=size, firing_normals=normals,
                                             padding=padding, ray_mesh=ray_mesh, progress=progress)
    if "thickness" in kinds:
        out["thickness"] = bake.bake_thickness(lp, low_tris, hard, low_uvs, cp, hp, high_tris,
                                               resolution=size, firing_normals=normals,
                                               padding=padding, ray_mesh=ray_mesh, progress=progress)
    if "curv" in kinds and out.get("normal") is not None:
        out["curv"] = bake.curvature_from_normal_map(out["normal"])
    return out


def bake_pair(low_path, high_path, *, cage_path=None, out_dir=".", size=1024,
              supersample=1, padding=0, push=None, ao_samples=64,
              maps=("normal",), flip_green=False, progress=None):
    """Bake a low/high (+ optional cage) pair to per-type PNGs in `out_dir`. `maps` is any
    of 'normal', 'objnormal', 'ao', 'curv'. Returns the written paths."""
    notify = progress or (lambda _m: None)
    scene_low = meshio.load_scene(low_path, with_uvs=True)
    scene_high = meshio.load_scene(high_path, with_uvs=False)
    hard, normals, cage_pts = _build_cage(scene_low["merged"], cage_path, None, push)
    images = _bake_maps(scene_low, scene_high, hard, normals, cage_pts, set(maps),
                        size=size, supersample=supersample, padding=padding,
                        ao_samples=ao_samples, flip_green=flip_green, explode=0.0,
                        progress=notify)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(low_path))[0]
    suffix = {"normal": "_normal", "objnormal": "_objnormal", "ao": "_ao",
              "curv": "_curv", "height": "_height", "position": "_position",
              "thickness": "_thickness"}
    written = []
    for kind, img in images.items():
        if img is None:
            continue
        path = os.path.join(out_dir, f"{stem}{suffix[kind]}.png")
        bake._write_png(path, img)
        written.append(path)
        notify(f"wrote {path}")
    return written


def bake_project(project_path, *, out_dir=None, progress=None):
    """Load a `.cbcproj` and bake its recipe with the saved cage edits and bake settings,
    packing the recipe's output PNGs. Returns the written paths."""
    notify = progress or (lambda _m: None)
    data = project.load(project_path)
    base = os.path.dirname(os.path.abspath(project_path))
    paths = data.get("paths") or {}
    low_path = project.resolve(paths.get("low"), base)
    high_path = project.resolve(paths.get("high"), base)
    cage_path = project.resolve(paths.get("cage"), base)
    if not high_path:
        raise ValueError("project has no high poly; cannot bake")
    edits = data.get("edits") or {}
    rec = _recipe.Recipe.from_dict(data["recipe"]) if data.get("recipe") else None
    if rec is None:
        raise ValueError("project has no recipe to bake")

    size = tuple(edits.get("bake_size", (1024, 1024)))
    scene_low = meshio.load_scene(low_path, with_uvs=True)
    scene_high = meshio.load_scene(high_path, with_uvs=False)
    hard, normals, cage_pts = _build_cage(scene_low["merged"], cage_path, edits, None)

    kinds = set()
    for m in rec.bake_maps:
        kinds.add("objnormal" if (m.kind == "normal" and m.space == "object") else m.kind)
    images = _bake_maps(
        scene_low, scene_high, hard, normals, cage_pts, kinds, size=size,
        supersample=int(edits.get("supersample", 1)), padding=int(edits.get("padding", 0)),
        ao_samples=int(edits.get("ao_samples", 64)), flip_green=bool(edits.get("flip_green")),
        explode=float(edits.get("explode", 0.0)), progress=notify)

    # Resolve each recipe map id to its baked buffer (object vs tangent normal).
    baked = {}
    for m in rec.bake_maps:
        if m.kind == "normal":
            img = images.get("objnormal") if m.space == "object" else images.get("normal")
        else:
            img = images.get(m.kind)
        if img is not None:
            baked[m.id] = img

    lp_name = os.path.splitext(os.path.basename(low_path))[0]
    files = bake.pack_outputs(baked, rec, lp_name)
    out_dir = out_dir or os.path.dirname(low_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for fname, img in files.items():
        path = os.path.join(out_dir, fname)
        bake._write_png(path, img)
        written.append(path)
        notify(f"wrote {path}")
    return written
