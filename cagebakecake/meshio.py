"""Mesh loading.

USD is the internal interchange format (see docs/environment.md). Source FBX/OBJ are
converted to USD offline via tools/blender_to_usd.py; this module reads USD into a
pyvista.PolyData with point normals, which is what the rest of the app consumes.

Everything downstream is format-blind, so adding another source format means adding a
branch here and nothing else.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from pxr import Usd, UsdGeom


def _largest_mesh_prim(stage: Usd.Stage):
    """Pick the UsdGeom.Mesh prim with the most points.

    FBX LOD groups come through as several Mesh prims (see docs/environment.md);
    highest point count is a sane default that also works for single-mesh assets.
    Returns (prim, UsdGeom.Mesh) or raises if the stage has no mesh.
    """
    best = None
    best_n = -1
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            pts = mesh.GetPointsAttr().Get()
            n = len(pts) if pts else 0
            if n > best_n:
                best, best_n = mesh, n
    if best is None:
        raise ValueError("no UsdGeom.Mesh prim found in stage")
    return best


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


def load_mesh(path: str) -> pv.PolyData:
    """Load a USD file into a pyvista.PolyData with world-space points and normals."""
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError(f"could not open USD stage: {path}")
    mesh = _largest_mesh_prim(stage)

    points = np.asarray(mesh.GetPointsAttr().Get(), dtype=np.float64)

    # Bake the prim's world transform into the points (FBX import often carries a
    # scale/axis xform). USD is row-vector * row-major-matrix, so points @ M.
    xform = UsdGeom.XformCache().GetLocalToWorldTransform(mesh.GetPrim())
    mat = np.asarray(xform, dtype=np.float64).reshape(4, 4)
    homog = np.hstack([points, np.ones((len(points), 1))])
    points = (homog @ mat)[:, :3]

    faces = _faces_to_vtk(
        mesh.GetFaceVertexCountsAttr().Get(),
        mesh.GetFaceVertexIndicesAttr().Get(),
    )

    poly = pv.PolyData(points, faces)
    # Consistent point normals regardless of what the file stored.
    poly = poly.compute_normals(
        cell_normals=False, point_normals=True, auto_orient_normals=True
    )
    return poly


def load_faces_uvs(path: str, with_uvs: bool = True):
    """Triangulated faces (and per-corner UVs) for baking, aligned to load_mesh's points.

    `load_mesh` returns a render-ready PolyData but drops UVs and keeps quads/ngons; the
    bake needs triangles and the low poly's faceVarying `st` layout. This fan-triangulates
    the largest mesh prim and carries `st` through the same split, so uvs[f] holds the UVs
    of triangle f's three corners. Vertex indices match load_mesh's point order, so the
    triangles index straight into that PolyData's points / cage points.

    Returns (tris (F,3) int64, uvs (F,3,2) float64 or None). `with_uvs=False` skips the
    UV read entirely - used for the high poly, which only supplies hit geometry.
    """
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError(f"could not open USD stage: {path}")
    mesh = _largest_mesh_prim(stage)
    counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int64)
    indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int64)

    # Fan triangulation: a face of c corners -> c-2 triangles (corner 0, k, k+1). Track
    # each triangle corner's position in the original corner stream so a faceVarying
    # primvar can be split identically.
    ntri = counts - 2
    starts = np.zeros(len(counts), dtype=np.int64)
    starts[1:] = np.cumsum(counts)[:-1]
    face = np.repeat(np.arange(len(counts)), ntri)
    k = np.arange(int(ntri.sum())) - np.repeat(np.cumsum(ntri) - ntri, ntri) + 1
    c0 = starts[face]
    corner = np.stack([c0, c0 + k, c0 + k + 1], axis=1)  # (F,3) corner-stream indices
    tris = indices[corner]                                # (F,3) vertex ids

    uvs = None
    if with_uvs:
        primvar = UsdGeom.PrimvarsAPI(mesh.GetPrim()).GetPrimvar("st")
        if primvar and primvar.HasValue():
            flat = np.asarray(primvar.ComputeFlattened(), dtype=np.float64)
            interp = primvar.GetInterpolation()
            if interp == UsdGeom.Tokens.faceVarying:
                uvs = flat[corner]   # one UV per corner -> (F,3,2)
            elif interp == UsdGeom.Tokens.vertex:
                uvs = flat[tris]     # one UV per vertex
    return tris, uvs
