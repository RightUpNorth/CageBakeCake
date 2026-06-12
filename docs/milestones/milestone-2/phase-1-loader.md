# Phase 2.1 - Mesh loader

## Goal

A single `meshio.load_mesh(path)` that returns NumPy vertices, faces, and unit vertex
normals, wrapped into a `pyvista.PolyData`, for all supported formats.

## Tasks

- [ ] Load OBJ/PLY/STL natively through PyVista.
- [ ] Load FBX/glTF through trimesh (assimp backend) and convert to the same
      NumPy vertices/faces representation.
- [ ] Request **no vertex splitting** from the FBX/assimp path where the format
      allows it (split vertices break correspondence - see the FBX caveat).
- [ ] Compute/normalize unit vertex normals (PyVista `compute_normals`) when the
      file does not provide them.
- [ ] Return a consistent structure (vertices, faces, vertex_normals) and a
      `pyvista.PolyData` regardless of source format.
- [ ] Raise a clear error on unsupported formats or unreadable files.

## Notes

- OBJ is the reliable interchange path; FBX is supported but defensively handled.
- Keep this module GUI-free so it is unit-testable (round-trip a tiny OBJ).
