"""Milestone 1 spike: pick a cage vertex, drag a handle, move that one vertex along
its low-poly normal.

Scope is deliberately small (see docs/milestones/milestone-1-pick-gizmo.md):
no displacement/opacity sliders, no shader, no HDR, no baking. The cage here is an
in-memory duplicate of the low poly (the "create cage" idea), pushed out a little so
it is visible.

Interaction: hovering highlights the nearest cage vertex (white); left-click selects
it; a draggable yellow handle appears and a red tube shows the normal axis. Dragging
is constrained to that normal via cage.project_onto_normal, so exactly one vertex
moves, in/out along its normal. Edits are stored in manual_delta so a later global
slider can layer on top (Milestone 3).
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
import vtk

from . import cage, meshio


class CageEditor:
    def __init__(self, mesh_path: str, global_push: float = 0.03, off_screen: bool = False):
        self.low = meshio.load_mesh(mesh_path)
        self.base = np.asarray(self.low.points, dtype=np.float64).copy()
        self.normals = np.asarray(self.low.point_normals, dtype=np.float64).copy()
        self.global_push = float(global_push)
        self.manual_delta = np.zeros_like(self.base)
        self.selected: int | None = None

        # Cage starts as a duplicate of the low poly, composed to its display position.
        self.cage = self.low.copy()
        self._recompose()

        diag = float(np.linalg.norm(np.ptp(self.base, axis=0)))
        self._handle_radius = diag * 0.02
        self._axis_len = diag * 0.12

        self.pl = pv.Plotter(off_screen=off_screen)
        self._add_actors()

    # --- geometry -----------------------------------------------------------
    def _recompose(self) -> None:
        self.cage.points = cage.compose(
            self.base, self.normals, self.global_push, self.manual_delta
        )

    def _add_actors(self) -> None:
        self.pl.add_mesh(self.low, style="wireframe", color="white", line_width=1, name="low")
        self.cage_actor = self.pl.add_mesh(
            self.cage, color="cyan", opacity=0.35, name="cage", show_edges=False
        )
        # Show the cage vertices so they can be seen and aimed at.
        self.pl.add_mesh(
            self.cage,
            style="points",
            color="orange",
            point_size=5,
            render_points_as_spheres=True,
            name="cage_pts",
        )
        # Hover marker (hidden until the cursor is over the cage). One actor, moved
        # by SetPosition rather than rebuilt each mouse move.
        self._hover_picker = vtk.vtkCellPicker()
        self._hover_picker.SetTolerance(0.005)
        hover_sphere = pv.Sphere(radius=self._handle_radius * 0.6)
        self._hover_actor = self.pl.add_mesh(hover_sphere, color="white", name="hover_highlight")
        self._hover_actor.SetVisibility(False)

        self.pl.add_axes()
        self.pl.set_background("slategray")

    # --- interaction --------------------------------------------------------
    def _nearest_vertex(self, point) -> int:
        p = np.asarray(point, dtype=np.float64).ravel()[:3]
        return int(np.argmin(np.sum((self.cage.points - p) ** 2, axis=1)))

    def _on_pick(self, picked_point) -> None:
        idx = self._nearest_vertex(picked_point)
        self.selected = idx
        print(f"[pick] vertex {idx} at {np.round(self.cage.points[idx], 3)}")
        self._show_handle()

    def _on_hover(self, *_args) -> None:
        x, y = self.pl.iren.interactor.GetEventPosition()
        self._hover_picker.Pick(x, y, 0, self.pl.renderer)
        if self._hover_picker.GetCellId() >= 0:
            idx = self._nearest_vertex(self._hover_picker.GetPickPosition())
            self._hover_actor.SetPosition(*self.cage.points[idx])
            self._hover_actor.SetVisibility(True)
        else:
            self._hover_actor.SetVisibility(False)
        self.pl.render()

    def _show_handle(self) -> None:
        i = self.selected
        anchor = self.cage.points[i]
        self._draw_axis(i)
        self._highlight_selected(i)
        # Replace the previous handle instead of stacking a new one each pick.
        self.pl.clear_sphere_widgets()
        self.pl.add_sphere_widget(
            self._on_drag,
            center=anchor,
            radius=self._handle_radius,
            color="yellow",
        )

    def _draw_axis(self, i: int) -> None:
        anchor = self.cage.points[i]
        n = self.normals[i]
        # Outward only (the inward half is buried inside the solid mesh), as a thick
        # tube rendered on top so it is not lost through the transparent cage.
        line = pv.Line(anchor, anchor + n * self._axis_len)
        actor = self.pl.add_mesh(
            line, color="red", line_width=8, render_lines_as_tubes=True, name="normal_axis"
        )
        actor.mapper.SetResolveCoincidentTopologyToPolygonOffset()
        actor.prop.SetLineWidth(8)

    def _highlight_selected(self, i: int) -> None:
        # A bright marker so the selected vertex stands out among the orange points.
        marker = pv.Sphere(radius=self._handle_radius * 0.55, center=self.cage.points[i])
        self.pl.add_mesh(marker, color="lime", name="sel_highlight")

    def _on_drag(self, new_center) -> None:
        i = self.selected
        if i is None:
            return
        projected = cage.project_onto_normal(new_center, self.base[i], self.normals[i])
        # Store as the extra on top of base + global push, matching cage.compose.
        self.manual_delta[i] = projected - (self.base[i] + self.normals[i] * self.global_push)
        pts = self.cage.points.copy()
        pts[i] = projected
        self.cage.points = pts
        self._draw_axis(i)

    # --- lifecycle ----------------------------------------------------------
    def run(self) -> None:
        self.pl.enable_surface_point_picking(
            callback=self._on_pick,
            show_message=False,
            show_point=True,
            point_size=12,
            color="magenta",
            left_clicking=True,
        )
        self.pl.iren.add_observer("MouseMoveEvent", self._on_hover)
        self.pl.add_text(
            "Hover shows the nearest vertex (white). Left-click to select.\n"
            "Drag the yellow ball along the red normal axis.",
            font_size=10,
            name="help",
        )
        self.pl.show()

    def screenshot(self, path: str) -> None:
        self.pl.show(auto_close=False)
        self.pl.screenshot(path)
