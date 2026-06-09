# Phase 1.3 - Apply and persist the edit

## Goal

Turn a drag into a persistent per-vertex offset and update only the affected vertex.

## Tasks

- [ ] On drag, compute the new position from the handle (constrained to the normal
      by default).
- [ ] Convert it to an offset and store it in `manual_delta[selected]` (the
      per-vertex array introduced in `docs/cage-model.md`).
- [ ] Write the resulting position into `cage.points[selected]` and trigger a
      re-render.
- [ ] Verify exactly one vertex moves and neighbors are untouched.
- [ ] Confirm the edit survives a later global-displacement change (the value lives
      in `manual_delta`, recomputed as `base + normal*slider + manual_delta`).

## Notes

- `manual_delta` is the contract with Milestone 3: the displacement slider must read
  through it, never overwrite it.
- Re-render by updating the existing `PolyData` points in place rather than
  re-adding the actor, to keep interaction smooth.
