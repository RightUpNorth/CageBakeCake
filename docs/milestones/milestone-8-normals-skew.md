# Milestone 8 - Hard/soft normals: watertight cage + skew

## Goal

Make the cage push use **soft (welded) normals** so the cage stays watertight over a
hard-edged low poly, while leaving the low poly's hard normals untouched (they author
the bake). Then add **skew**: a per-region hard<->soft blend of the ray firing
direction, the way the Houdini Copernicus / Labs Maps Baker automates a soft cage.

## Why

The cage and the low poly consume normals at different bake stages (see
docs/cage-model.md):

- Hard normals (splits at hard edges, UV seams, smoothing groups) define the baked
  tangent-space map and tangent basis - never flatten them.
- The cage push must use soft normals. Peaking along split normals makes coincident
  seam points diverge, tearing the shell -> rays leak -> black spots / skirting.

The editor currently pushes along the low poly's per-point normals, which are soft
only because the USD assets happen to be welded. On a genuinely hard-edged low poly
the cage would tear. This milestone makes the soft-normal step explicit, then adds
the skew control for per-region tuning.

## Phases

1. [Phase 8.1 - Soft (welded) cage normals](milestone-8/phase-1-soft-cage-normals.md) - **done**
2. [Phase 8.2 - Skew (hard/soft firing-direction blend)](milestone-8/phase-2-skew-blend.md)

## Exit criteria

- Cage push uses one averaged normal per welded position; the cage is watertight
  across hard edges/seams on a hard-edged low poly.
- The low poly's hard vertex normals are unchanged (the bake still records sharp
  transitions).
- A skew control blends the firing direction between the low poly's real normals and
  the softened copy, weighted per region (uniform first, paintable later).

## References

- `docs/cage-model.md` - hard vs soft normals principle.
- `docs/baking.md` and [Milestone 7](milestone-7-bake.md) - skew sets ray direction
  at bake time.
