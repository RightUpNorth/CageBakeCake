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
- **`vtkAxesTransformWidget` ruled out:** introspection showed its representation
  exposes no usable transform readback (`GetTransform` absent), so wiring drag ->
  vertex motion through it is not viable. Good that this was checked before building.
- **Chosen for now: constraint-mode toggle on the proven handle.** Reuse the working
  sphere widget and switch which constraint the drag applies:
  - `[1]` displace mode -> `cage.project_onto_normal` (in/out along the normal),
    shown as the red normal axis.
  - `[2]` slide mode -> `cage.project_onto_plane` (motion in the tangent plane),
    shown as a green disc.
  This delivers the requested "displace vs slide along surface" function reliably,
  with zero custom mouse-interception risk.

Built on top of the confirmed constraint logic: a **3-arrow gizmo** at the selected
vertex (blue = displace along normal, red/green = slide in the tangent plane, basis
from `cage.tangent_basis`). **Hovering an arrow selects that constraint** - the hover
cell-picker's actor is matched to the arrow by C++ address (validated: a
`vtkCellPicker` actor matches the stored pyvista actor by `GetAddressAsString`), and
the arrows follow the vertex during a drag via `SetPosition`. Keys `1`/`2` remain as
a fallback. This avoids custom drag-math/camera-interception by reusing the proven
sphere widget for the actual drag.

Now building the grab-the-handle gizmo (the ball is dropped): the handles themselves
are dragged. Custom manipulator via raw interactor observers (press/move/release at
priority above the camera style):

- Press over a handle -> begin drag; the camera is suppressed by swapping the
  interactor style to `vtkInteractorStyleUser` for the duration, plus aborting the
  press event (`interactor.GetCommand(tag).SetAbortFlag(1)`) so the trackball never
  starts a rotate. Confirmed available: interactor `GetCommand`, command
  `SetAbortFlag`. This is the load-bearing mechanism being spiked.
- Move while dragging -> cursor ray (renderer `DisplayToWorld`) is projected onto the
  handle's line (`cage.closest_point_on_axis`, normal) or plane
  (`cage.ray_plane_intersect`, tangent); the resulting target drives the same
  manual_delta + soft-selection pipeline.
- Selection happens on a left-click (press+release at the same spot) that is NOT over
  a handle, so you cannot accidentally select another vertex while dragging.
- Hover highlights the handle under the cursor (yellow).

Camera suppression confirmed working in the live window (the view stays still while
dragging a handle). Both handles are now implemented: a **red normal arrow**
(displace via `closest_point_on_axis`) and a **green tangent-plane ring** (slide via
`ray_plane_intersect`). Grabbing a handle sets the mode from its address->mode map;
the drag, gizmo-follow, and soft-selection paths are shared. Selection happens on
press (pyvista swallows release events; see issue #4976), so dragging empty
background orbits while clicking the mesh selects.

Gotchas seen: the free-drag sphere can drift off the constraint while the vertex
snaps to it (the arrow-gizmo polish fixes this); the normal line must be drawn
outward-only as an on-top tube or it hides inside the solid mesh.

## Notes

- Default motion is normal-constrained (1 axis along the normal). The sphere-widget
  path plus `project_onto_normal` is also the foundation for the stretch-goal free
  3-axis mode, so prefer keeping that math path available.
- Reference: `docs/interaction.md` (gizmo), `docs/cage-model.md` (orientation).
