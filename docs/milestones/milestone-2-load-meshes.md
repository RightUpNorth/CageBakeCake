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

## Status

Implemented. `CageEditor(low_path, high_path, cage_path)` loads the low poly (cage
matches its topology + normals), the high poly (opaque, smooth-shaded - PBR is M5),
and an optional cage file (correspondence-checked: count must match the low poly).
With no cage file the cage is an in-memory copy of the low poly. The CLI defaults to
the Mat Ball low/high pair (`MatBall_LP.usdc` + `MatBall.usdc`).

**Create cage** ([c] key): writes a topology-matched cage to `<low_stem>_cage.usd`
by duplicating the low-poly USD (the chosen "USD copy" approach - identical topology,
correspondence guaranteed). Saving an offset/edited cage is a later "save" action.

**Undo/redo** ([z]/[y]): added per request - snapshots `manual_delta` after each
completed drag, with redo-branch truncation on a new edit. Cross-cutting, not part of
the original milestone phases.

## References

- `docs/architecture.md` - `meshio` module and FBX caveat.
- `docs/cage-model.md` - correspondence validation.
- `docs/interaction.md` - the three actors table.
