"""Mesh loading.

USD is the internal interchange format (see docs/environment.md). Source FBX/OBJ are
converted to USD offline via tools/blender_to_usd.py; this module reads USD into
pyvista.PolyData with point normals, which is what the rest of the app consumes.

A USD file can hold several mesh prims (FBX LOD groups, or a low poly split into
material parts - e.g. bin_lp's uv_fix + uv_fix_001). `load_scene` returns each prim as
its own display part *and* a merged mesh (with cached triangulation / UVs) for the cage
and the bake, which need one topology-matched mesh. Loading all prims - rather than just
the largest - is what lets the per-mesh visibility checklist exist and stops smaller
prims being silently dropped.

Everything downstream is format-blind, so adding another source format means adding a
branch here and nothing else.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from pxr import Usd, UsdGeom


def _iter_mesh_prims(stage: Usd.Stage):
    """Yield (prim, UsdGeom.Mesh) for every non-empty mesh prim, in traversal order.

    Traversal order is the canonical ordering used everywhere here, so the merged mesh,
    the cached triangulation and the per-part ranges all line up.
    """
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            pts = mesh.GetPointsAttr().Get()
            if pts is not None and len(pts) > 0:
                yield prim, mesh


def _faces_to_vtk(face_vertex_counts, face_vertex_indices) -> np.ndarray:
    """Build a VTK/pyvista flat face array [n, i0..in-1, n, ...] from USD topology."""
    counts = np.asarray(face_vertex_counts, dtype=np.int64)
    indices = np.asarray(face_vertex_indices, dtype=np.int64)
    n = counts.size
    faces = np.empty(indices.size + n, dtype=np.int64)
    insert_at = np.empty(n, dtype=np.int64)
    insert_at[0] = 0
    insert_at[1:] = np.cumsum(counts)[:-1] + np.arange(1, n)
    faces[insert_at] = counts
    mask = np.ones(faces.size, dtype=bool)
    mask[insert_at] = False
    faces[mask] = indices
    return faces


def _to_canonical_frame(points: np.ndarray, stage) -> np.ndarray:
    """Normalize world points into a canonical metres / Z-up frame.

    Different converters encode the same mesh differently: Blender's USD export bakes a
    0.01 scale and a Y->Z up-axis rotation into the prim transform (stage upAxis=Z,
    metersPerUnit=1), while tools/fbx_ascii_to_usd.py writes the raw Y-up centimetre
    points (upAxis=Y, the USD default metersPerUnit=0.01). Honoring metersPerUnit and the
    stage up-axis here puts both in the same world space, so a low poly from one converter
    and a high poly from the other still line up for baking.
    """
    points = points * UsdGeom.GetStageMetersPerUnit(stage)
    if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y:
        # Match Blender's Y-up -> Z-up: (x, y, z) -> (x, -z, y).
        points = points[:, [0, 2, 1]]
        points[:, 1] *= -1.0
    return points


def _prim_points(prim, mesh, stage, cache) -> np.ndarray:
    """World-space, canonical-frame points for one prim (bakes in its xform)."""
    points = np.asarray(mesh.GetPointsAttr().Get(), dtype=np.float64)
    # USD is row-vector * row-major-matrix, so points @ M.
    mat = np.asarray(cache.GetLocalToWorldTransform(prim), dtype=np.float64).reshape(4, 4)
    homog = np.hstack([points, np.ones((len(points), 1))])
    points = (homog @ mat)[:, :3]
    return _to_canonical_frame(points, stage)


def _fan_triangulate(counts: np.ndarray, indices: np.ndarray):
    """Fan-triangulate a polygon stream. A face of c corners -> c-2 triangles
    (corner 0, k, k+1). Returns (tris (F,3) vertex ids, corner (F,3) corner-stream
    indices) so a faceVarying primvar can be split the same way."""
    ntri = counts - 2
    starts = np.zeros(len(counts), dtype=np.int64)
    starts[1:] = np.cumsum(counts)[:-1]
    face = np.repeat(np.arange(len(counts)), ntri)
    k = np.arange(int(ntri.sum())) - np.repeat(np.cumsum(ntri) - ntri, ntri) + 1
    c0 = starts[face]
    corner = np.stack([c0, c0 + k, c0 + k + 1], axis=1)
    tris = indices[corner]
    return tris, corner


def _read_st(mesh, corner: np.ndarray, tris: np.ndarray):
    """Per-corner UVs (F,3,2) for a prim, or None if it has no `st` primvar."""
    primvar = UsdGeom.PrimvarsAPI(mesh.GetPrim()).GetPrimvar("st")
    if not (primvar and primvar.HasValue()):
        return None
    flat = np.asarray(primvar.ComputeFlattened(), dtype=np.float64)
    interp = primvar.GetInterpolation()
    if interp == UsdGeom.Tokens.faceVarying:
        return flat[corner]
    if interp == UsdGeom.Tokens.vertex:
        return flat[tris]
    return None


def _load_prims(path: str, with_uvs: bool):
    """Read every mesh prim into raw arrays (traversal order). Each entry has: name,
    points (Vi,3), counts, indices (local), tris (Fi,3 local), uvs (Fi,3,2) or None."""
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError(f"could not open USD stage: {path}")
    cache = UsdGeom.XformCache()
    prims = []
    for prim, mesh in _iter_mesh_prims(stage):
        points = _prim_points(prim, mesh, stage, cache)
        counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int64)
        indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int64)
        tris, corner = _fan_triangulate(counts, indices)
        uvs = _read_st(mesh, corner, tris) if with_uvs else None
        prims.append(
            {"name": prim.GetName(), "points": points, "counts": counts,
             "indices": indices, "tris": tris, "uvs": uvs}
        )
    if not prims:
        raise ValueError(f"no UsdGeom.Mesh prim found in stage: {path}")
    return prims


def _poly(points: np.ndarray, counts: np.ndarray, indices: np.ndarray) -> pv.PolyData:
    poly = pv.PolyData(points, _faces_to_vtk(counts, indices))
    return poly.compute_normals(cell_normals=False, point_normals=True,
                                auto_orient_normals=True)


def load_scene(path: str, with_uvs: bool = True) -> dict:
    """Load a USD file as a scene of parts plus a merged mesh.

    Returns a dict:
      parts  - list of (name, pv.PolyData) per prim, for individually toggleable display
      merged - one pv.PolyData (all prims concatenated, point normals) for the cage and as
               the bake's hit geometry; its point order is parts concatenated in order
      tris   - (F,3) merged triangulation, indices into `merged`'s points
      uvs    - (F,3,2) merged per-corner UVs, or None if any prim lacks `st`
      ranges - list of (name, start, count) point spans of each part within `merged`,
               so a per-merged-point array (e.g. the baked UVs) can be sliced per part
    """
    prims = _load_prims(path, with_uvs)
    parts = [(p["name"], _poly(p["points"], p["counts"], p["indices"])) for p in prims]

    pts, counts, idx, tris, ranges = [], [], [], [], []
    have_uv = with_uvs and all(p["uvs"] is not None for p in prims)
    uvs_list = []
    offset = 0
    for p in prims:
        n = len(p["points"])
        ranges.append((p["name"], offset, n))
        pts.append(p["points"])
        counts.append(p["counts"])
        idx.append(p["indices"] + offset)
        tris.append(p["tris"] + offset)
        if have_uv:
            uvs_list.append(p["uvs"])
        offset += n

    if len(prims) == 1:
        merged = parts[0][1]  # reuse; avoids duplicating a multi-million-point high poly
    else:
        merged = _poly(np.concatenate(pts), np.concatenate(counts), np.concatenate(idx))
    return {
        "parts": parts,
        "merged": merged,
        "tris": np.concatenate(tris) if len(tris) > 1 else tris[0],
        "uvs": np.concatenate(uvs_list) if have_uv else None,
        "ranges": ranges,
    }


def load_mesh(path: str) -> pv.PolyData:
    """Merged mesh only (point normals). Used for the cage, which is one mesh."""
    return load_scene(path, with_uvs=False)["merged"]


def load_faces_uvs(path: str, with_uvs: bool = True):
    """Merged (tris (F,3), uvs (F,3,2) or None) - the bake's low-poly input. Kept for
    callers that only need the triangulation; `load_scene` returns the same arrays."""
    scene = load_scene(path, with_uvs)
    return scene["tris"], scene["uvs"]
