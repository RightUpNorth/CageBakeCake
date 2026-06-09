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
