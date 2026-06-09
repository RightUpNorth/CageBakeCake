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

## Exit criteria

- Pressing Bake produces an `N x N` tangent-space normal-map PNG.
- Flat regions encode near `(128, 128, 255)`; bumps deviate in the expected
  direction.
- A low poly without UVs fails with a clear error.
- The baked map previews on the low poly.

## References

- `docs/baking.md` - full algorithm, inputs, scope.
- `docs/architecture.md` - `bake` module, trimesh ray caster, embree backend.
