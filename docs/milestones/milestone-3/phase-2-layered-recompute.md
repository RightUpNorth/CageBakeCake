# Phase 3.2 - Layered recompute

## Goal

Compose the cage position from the base, the global slider, and per-vertex manual
edits so the two controls coexist.

## Tasks

- [ ] Recompute cage points as `base + normal * slider_value + manual_delta` on every
      slider change.
- [ ] Read `manual_delta` (never overwrite it) so gizmo edits persist.
- [ ] Centralize this recompute in one method both the slider and the gizmo call, to
      avoid divergent update paths.
- [ ] Verify: edit a vertex, then sweep the slider - the edited vertex keeps its
      relative offset throughout.

## Notes

- This is the contract established in Milestone 1 Phase 1.3. Both controls write
  through the same composition.
- Reference: `docs/cage-model.md` (layering manual edits).
