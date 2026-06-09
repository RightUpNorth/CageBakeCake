# Phase 8.2 - Skew (hard/soft firing-direction blend)

## Goal

Blend the ray firing direction between the low poly's real (possibly hard) normals
and a softened copy, weighted by a per-region control - the skew input that the
Houdini Copernicus / Labs Maps Baker uses to automate a soft cage.

## Tasks

- [ ] Keep both normal sets: hard (low poly per-point) and soft (welded/averaged from
      Phase 8.1).
- [ ] Add a skew weight in [0, 1] per vertex: 0 = fire along the hard normal, 1 =
      fire along the soft normal. Start with a single uniform value (a slider).
- [ ] Firing direction = `normalize(lerp(hard_n, soft_n, skew))`, used as the cage
      push direction and, at bake time, the ray direction (Milestone 7).
- [ ] Later: make skew a paintable per-region map (soft on flat panels, near-hard at
      crisp edges) instead of a single value.

## Notes

- Skew is an alternative/complement to hand-editing the cage: it nudges ray direction
  without moving cage points. The manual gizmo cage edits and the skew blend can
  coexist.
- Integrates with the bake ray cast in
  [Milestone 7](../milestone-7-bake.md) - skew decides direction, the cage decides
  the outer bound.
