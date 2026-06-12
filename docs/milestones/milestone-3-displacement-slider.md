# Milestone 3 - Displacement slider

## Goal

A float slider that pushes the whole cage outward along the low-poly normals, layered
so it never wipes out per-vertex gizmo edits.

## Phases

1. [Phase 3.1 - Slider widget](milestone-3/phase-1-slider.md)
2. [Phase 3.2 - Layered recompute](milestone-3/phase-2-layered-recompute.md)

## Status

Implemented (both the displacement and transparency sliders, the latter from
Milestone 4 folded in). `add_slider_widget` at the bottom-left drives `global_push`
-> `_recompose` (`base + normals*push + manual_delta`) -> `_gizmo_follow`; a
bottom-right slider drives `cage_actor.prop.opacity`. Verified headless: per-vertex
edits (manual_delta) are preserved as the offset slider moves, and the cage inflates
along normals.

## Exit criteria

- Moving the slider inflates/deflates the cage smoothly along normals.
- Vertices edited in Milestone 1 keep their manual offset as the slider moves.

## References

- `docs/cage-model.md` - displacement math and layering.
- `docs/interaction.md` - displacement slider.
