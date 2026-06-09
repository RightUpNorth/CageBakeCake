# Phase 1.2 - Normal-oriented handle

## Goal

Show a draggable handle at the selected vertex, oriented to its low-poly normal, and
decide which PyVista primitive to use. This phase is a deliberate spike: confirm the
primitive before committing.

## Tasks

- [ ] Spike `add_line_widget` with the line placed along
      `lowpoly_normals[selected]` through `cage.points[selected]`; confirm the drag
      callback yields a usable axis-constrained position.
- [ ] If the line widget is insufficient, spike `add_sphere_widget` for free drag,
      then clamp with `cage.project_onto_normal(point, anchor, normal)`.
- [ ] Only if both fall short, evaluate raw VTK `vtkAxesTransformWidget`.
- [ ] Record the chosen primitive and the reason in this file (update the Decision
      section below).
- [ ] Place and orient the handle at the selected vertex; remove/hide it on
      deselect and re-create it on the next selection.

## Decision

Spike progress (in order):

- **Sphere widget + project_onto_normal** is confirmed working: pick fires on every
  left-click, the handle places at the nearest vertex, and the drag projects onto
  the normal. Good enough to prove the pick -> handle -> edit loop.
- **Next: upgrade to a real gizmo** oriented to the vertex's (tangent, bitangent,
  normal) frame, because the user wants axis-distinct motion: hover the depth
  (normal) axis to displace, or the tangent plane to slide along the surface. All
  VTK gizmo widgets are available in this build (`vtkAxesTransformWidget`,
  `vtkAxesTransformRepresentation`, `vtkAffineWidget`, `vtkHandleWidget`, etc.).
- **Approach:** spike ONE axis to confirmed-working before building the full
  three-axis gizmo (each visual check costs a user round-trip). Candidates:
  `vtkAxesTransformWidget` (real arrow gizmo, native axis constraint - verify
  readback + arbitrary-frame orientation first) vs three constrained handles reusing
  the proven sphere widget + a generalized project-onto-axis. Tangent basis = two
  unit vectors perpendicular to the normal (via cross products).

Gotchas seen: the free-drag sphere can drift off the normal line while the vertex
snaps to it (a real axis-constrained gizmo fixes this); the normal line must be
drawn outward-only as an on-top tube or it hides inside the solid mesh.

## Notes

- Default motion is normal-constrained (1 axis along the normal). The sphere-widget
  path plus `project_onto_normal` is also the foundation for the stretch-goal free
  3-axis mode, so prefer keeping that math path available.
- Reference: `docs/interaction.md` (gizmo), `docs/cage-model.md` (orientation).
