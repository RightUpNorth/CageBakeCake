# Milestone 1 - Pick, gizmo, single-vertex update

## Goal

Pick a single cage vertex in the viewport, show a handle oriented to its low-poly
normal, drag it, and have exactly that one vertex move - persisted as a per-vertex
manual offset.

## Why first

This is the only genuinely uncertain part of the project. Every other milestone is
standard PyVista wiring over headless math. Building this first retires the risk and
proves the interaction primitive (which PyVista widget reaches the behavior) before
the rest is built on top of it.

## Phases

1. [Phase 1.1 - Vertex picking](milestone-1/phase-1-picking.md)
2. [Phase 1.2 - Normal-oriented handle](milestone-1/phase-2-gizmo.md)
3. [Phase 1.3 - Apply and persist the edit](milestone-1/phase-3-apply.md)
4. [Phase 1.4 - Soft selection](milestone-1/phase-4-soft-selection.md)

## Exit criteria

- Clicking a cage vertex selects it and gives visible feedback.
- A handle appears oriented to that vertex's low-poly normal.
- Dragging moves only the selected vertex, along its normal by default.
- The move is stored in a `manual_delta` array (not just the render), so later
  milestones can layer the global slider on top without losing it.

## References

- `docs/interaction.md` - vertex picking and gizmo section.
- `docs/cage-model.md` - gizmo orientation and `project_onto_normal`.
