# Phase 7.1 - UV rasterization and sampling

## Goal

Turn the low-poly UV layout into per-texel sampling data: for each texel, the 3D
surface point, the interpolated normal, and a tangent basis.

## Tasks

- [ ] Validate the low poly has UVs; raise a clear error if not.
- [ ] Rasterize the low-poly UV triangles into the `N x N` buffer, recording the
      covering triangle and barycentric coordinates per covered texel.
- [ ] Interpolate the 3D surface position per texel (barycentric over triangle
      vertices).
- [ ] Interpolate the vertex normal per texel (the ray direction).
- [ ] Compute a per-texel tangent basis (tangent + bitangent from UV gradients,
      normal as the third axis).

## Notes

- Keep this headless in `bake.py`, operating on NumPy arrays, so it is testable.
- Reference: `docs/baking.md` (algorithm steps 2-3).
