# Phase 8.1 - Soft (welded) cage normals

## Goal

Push the cage along one averaged normal per welded position so the shell stays
watertight over a hard-edged low poly, without altering the low poly's hard normals.

## Tasks

- [ ] Add `cage.soft_vertex_normals(points, faces)` (headless, testable): fuse
      coincident positions, recompute one area/angle-averaged normal per welded
      position, and map it back to every coincident point. (fuse -> recompute -> peak)
- [ ] Use these soft normals for the cage push (`self.normals` for displacement and
      the gizmo's normal axis), keeping the low poly's own per-point (possibly hard)
      normals separate for the eventual bake.
- [ ] Verify watertightness: on a hard-edged test low poly, coincident seam points
      share a push direction and stay coincident at any offset (no gap).
- [ ] Confirm the smooth Mat Ball is unchanged (its welded normals already match).

## Notes

- This is the fuse->recompute->peak step described in docs/cage-model.md.
- Keep two normal sets on the editor: soft (cage push) and hard (low poly / bake).
- Euclidean position weld tolerance should be tight (exact-position or a tiny eps).
