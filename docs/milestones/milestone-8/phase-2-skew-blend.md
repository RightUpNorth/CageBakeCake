# Phase 8.2 - Skew (hard/soft firing-direction blend)

## Goal

Blend the ray firing direction between the low poly's real (possibly hard) normals
and a softened copy, weighted by a per-region control - the skew input that the
Houdini Copernicus / Labs Maps Baker uses to automate a soft cage.

## Tasks

- [x] Keep both normal sets: hard (low poly per-point) and soft (welded/averaged from
      Phase 8.1). `app` holds `hard_normals` and `soft_normals`.
- [x] Add a skew weight in [0, 1]: 0 = fire along the hard normal, 1 = soft. A single
      uniform value driven by the "Skew (hard..soft)" dock slider (`set_skew`).
- [x] Firing direction = `normalize(lerp(hard_n, soft_n, skew))` (`cage.blend_normals`),
      used as the cage push direction (`compose`) and the bake ray direction
      (`bake.bake(firing_normals=...)`). The tangent-space map stays encoded in the hard
      shading-normal frame, so skew bends the rays without distorting the map.
- [ ] Later: make skew a paintable per-region map (soft on flat panels, near-hard at
      crisp edges) instead of a single value.

## Status

Implemented as a uniform skew slider. `cage.blend_normals` is the pure firing-direction
math (covered by `tests/test_cage.py`); `bake.bake` now separates `firing_normals` (rays)
from `low_normals` (the encode/shading frame), with `tests/test_bake.py` pinning that a
tilted firing direction does not distort the encoded map. The per-region paintable skew
map remains a follow-up.

## Notes

- Skew is an alternative/complement to hand-editing the cage: it nudges ray direction
  without moving cage points. The manual gizmo cage edits and the skew blend can
  coexist.
- Integrates with the bake ray cast in
  [Milestone 7](../milestone-7-bake.md) - skew decides direction, the cage decides
  the outer bound.
