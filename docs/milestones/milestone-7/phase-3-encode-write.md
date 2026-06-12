# Phase 7.3 - Tangent-space encode and write

## Goal

Convert each hit normal into the texel's tangent space, encode to RGB, and write the
PNG.

## Tasks

- [ ] Transform each world-space hit normal into the texel's tangent basis.
- [ ] Encode `x,y,z` in `[-1,1]` to `[0,255]` RGB (flat surface -> ~`(128,128,255)`).
- [ ] Fill missed texels with a sensible default (flat normal) and note them.
- [ ] Write the `N x N` buffer to a PNG via `imageio`.
- [ ] Return the buffer (NumPy) from `bake` so the GUI can preview it without
      re-reading the file.

## Notes

- Matching a specific engine's tangent convention (e.g. MikkTSpace) is a refinement,
  not MVP.
- Reference: `docs/baking.md` (algorithm steps 6-7, tangent space).
