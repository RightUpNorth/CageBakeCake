# Milestone 7 - Bake button (heaviest)

## Goal

Bake a tangent-space normal map from the high poly onto the low poly, using the cage
to bound the projection, then preview it. The cage's whole purpose is realized here:
it supplies the outer ray limit per surface point.

## Phases

1. [Phase 7.1 - UV rasterization and sampling](milestone-7/phase-1-rasterize.md)
2. [Phase 7.2 - Cage-bounded ray casting](milestone-7/phase-2-raycast.md)
3. [Phase 7.3 - Tangent-space encode and write](milestone-7/phase-3-encode-write.md)
4. [Phase 7.4 - Bake button and preview](milestone-7/phase-4-button-preview.md)

## Status

Implemented (phases 7.1-7.4). `bake.py` is the headless core (rasterize low-poly UVs
-> cage-bounded ray cast via trimesh/embree -> tangent-space encode -> PNG), covered by
`tests/test_bake.py` on a synthetic known pair. `meshio.load_faces_uvs` adapts USD
(faceVarying `st`, quad triangulation) into the arrays the bake needs. In the app, `[b]`
bakes with the current cage as the ray bound and previews the map on the low poly
(toggling off the editing actors); pressing `[b]` again returns to editing.

Verified end-to-end through `CageEditor` on the aligned `bin_lp` + `bin_hp_nolid` pair:
709,759 / 710,117 covered texels hit (99.95%) at 1024x1024.

Two follow-ups surfaced, both outside the bake itself, both since **resolved**:

- **Converter consistency** (resolved). Blender's USD export bakes a 0.01 scale + a
  Y->Z up-axis into the prim transform, while `tools/fbx_ascii_to_usd.py` writes raw
  points; mixing them misaligned the meshes. `meshio._to_canonical_frame` now normalizes
  every stage into a metres / Z-up frame, so a low and high from different converters line
  up.
- **Cage push is absolute** (resolved). The cage offset now defaults to 3% of the mesh
  diagonal (scale-relative); `--push` still takes an absolute world-unit override.

## Exit criteria

- Pressing Bake produces an `N x N` tangent-space normal-map PNG.
- Flat regions encode near `(128, 128, 255)`; bumps deviate in the expected
  direction.
- A low poly without UVs fails with a clear error.
- The baked map previews on the low poly.

## References

- `docs/baking.md` - full algorithm, inputs, scope.
- `docs/architecture.md` - `bake` module, trimesh ray caster, embree backend.
