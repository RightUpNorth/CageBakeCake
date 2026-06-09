# Milestone 2 - Load the three meshes

## Goal

Load the low poly, cage, and high poly from disk, validate that the cage matches the
low poly, and show all three as distinctly styled actors in the viewport.

## Phases

1. [Phase 2.1 - Mesh loader](milestone-2/phase-1-loader.md)
2. [Phase 2.2 - Correspondence validation](milestone-2/phase-2-correspondence.md)
3. [Phase 2.3 - Register the actors](milestone-2/phase-3-actors.md)

## Exit criteria

- `meshio.load_mesh` returns vertices, faces, and unit vertex normals for OBJ/PLY/STL
  (native PyVista) and FBX/glTF (trimesh + assimp).
- A cage whose vertex count differs from the low poly is rejected with a clear error.
- The three meshes appear styled distinctly (high poly shaded opaque, low poly
  wireframe, cage semi-transparent).

## References

- `docs/architecture.md` - `meshio` module and FBX caveat.
- `docs/cage-model.md` - correspondence validation.
- `docs/interaction.md` - the three actors table.
