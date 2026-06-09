# Phase 8.1 - Soft (welded) cage normals

## Goal

Push the cage along one averaged normal per welded position so the shell stays
watertight over a hard-edged low poly, without altering the low poly's hard normals.

## Tasks

- [x] Add `cage.soft_vertex_normals(points, normals)` (headless, unit-tested): weld
      coincident positions and average the normals per welded position, mapping the
      result back to every coincident point.
- [x] Use these soft normals for the cage push (`self.normals` for displacement and
      the gizmo's normal axis); keep the low poly's hard normals on `self.hard_normals`
      for the eventual bake.
- [x] Verify watertightness on a synthetic hard-edged tent: coincident ridge verts
      weld to one normal (the average of the two panels), so they share a push
      direction at any offset.
- [x] Confirm the welded Mat Ball is unchanged (soft normals == stored normals).

## Notes

- Implemented by **welding the existing normals** rather than recomputing from faces:
  on a fully welded low poly each group is one vertex, so the stored normals are
  returned unchanged (no cage-shape regression); only coincident splits get averaged.
- Keeps two normal sets on the editor: soft (`normals`, cage push) and hard
  (`hard_normals`, low poly / bake).
- The benefit is only visible on a hard-edged low poly (the Mat Ball is fully
  welded, 0 splits).
