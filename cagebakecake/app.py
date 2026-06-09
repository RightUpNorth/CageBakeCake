"""Milestone 1 spike: pick a cage vertex and edit it with a grabbable gizmo.

Loads a low poly (the cage matches its topology), a high-poly reference, and
optionally a cage file; with no cage file the cage is an in-memory copy of the low
poly pushed out a little. Still no displacement/opacity sliders, no PBR/HDR, no
baking (later milestones). The [c] key writes a topology-matched cage to disk.

Interaction (custom manipulator - no separate drag ball):
  - Left-click a cage vertex (away from any handle) to select it.
  - Two grabbable handles appear: a red normal arrow (displace along the normal) and
    a green tangent-plane ring (slide across the surface). Hover highlights them.
  - Press and drag a handle -> the vertex moves under that constraint; the camera is
    suppressed during the drag so the view does not tumble, and no other vertex is
    selected by accident.
  - Soft selection ([o] toggle, [ ] radius) pulls neighbours along with a falloff.

Drag math is headless and unit-tested in cage.py (closest_point_on_axis for the
normal, ray_plane_intersect for the plane); edits go through manual_delta so a later
global slider can layer on top (Milestone 3).
"""

from __future__ import annotations

import os
import shutil

import numpy as np
import pyvista as pv
import vtk

from . import cage, meshio


class CageEditor:
    def __init__(
        self,
        low_path: str,
        high_path: str | None = None,
        cage_path: str | None = None,
        global_push: float = 0.03,
        off_screen: bool = False,
    ):
        self._low_path = low_path
        self._cage_path = cage_path
        self.low = meshio.load_mesh(low_path)
        self.normals = np.asarray(self.low.point_normals, dtype=np.float64).copy()
        self.high = meshio.load_mesh(high_path) if high_path else None

        # The cage's rest geometry: a loaded cage (topology-checked) or the low poly.
        if cage_path:
            cage_mesh = meshio.load_mesh(cage_path)
            cage.validate_correspondence(self.low.points, cage_mesh.points)
            self.base = np.asarray(cage_mesh.points, dtype=np.float64).copy()
        else:
            self.base = np.asarray(self.low.points, dtype=np.float64).copy()
        self.global_push = float(global_push)
        self.manual_delta = np.zeros_like(self.base)
        self.selected: int | None = None
        self.mode = "normal"  # "normal" = displace; "tangent" = slide (added next round)
        self._anchor: np.ndarray | None = None

        # Gizmo handles.
        self._giz: dict = {}              # name -> pyvista actor
        self._giz_mode: dict = {}         # actor address -> "normal" | "tangent"
        self._giz_color: dict = {}        # actor address -> base color
        self._giz_anchor: np.ndarray | None = None

        # Custom drag state.
        self._dragging = False
        self._saved_style = None
        self._press_tag = None
        self._release_tag = None

        # Undo/redo history of manual_delta snapshots.
        self._history: list[np.ndarray] = [self.manual_delta.copy()]
        self._hist_index = 0

        # Soft selection (proportional editing).
        self.soft_enabled = False
        self._md0: np.ndarray | None = None
        self._aff_idx = np.array([], dtype=np.int64)
        self._aff_w = np.array([], dtype=np.float64)
        self._soft_poly: pv.PolyData | None = None

        # Cage starts as a duplicate of the low poly, composed to its display position.
        self.cage = self.low.copy()
        self._recompose()

        diag = float(np.linalg.norm(np.ptp(self.base, axis=0)))
        self._handle_radius = diag * 0.02
        self._axis_len = diag * 0.14
        self.soft_radius = diag * 0.1
        self._push_max = diag * 0.3

        self.pl = pv.Plotter(off_screen=off_screen)
        self._handle_picker = vtk.vtkCellPicker()
        self._handle_picker.SetTolerance(0.01)
        self._mesh_picker = vtk.vtkCellPicker()
        self._mesh_picker.SetTolerance(0.005)
        self._add_actors()

    # --- geometry -----------------------------------------------------------
    def _recompose(self) -> None:
        self.cage.points = cage.compose(
            self.base, self.normals, self.global_push, self.manual_delta
        )

    def _add_actors(self) -> None:
        # High poly: the opaque, shaded reference the cage wraps (PBR comes in M5).
        if self.high is not None:
            self.pl.add_mesh(self.high, color="tan", smooth_shading=True, name="high")
        self.pl.add_mesh(self.low, style="wireframe", color="white", line_width=1, name="low")
        self.cage_actor = self.pl.add_mesh(
            self.cage, color="cyan", opacity=0.35, name="cage", show_edges=False
        )
        self.pl.add_mesh(
            self.cage, style="points", color="orange", point_size=5,
            render_points_as_spheres=True, name="cage_pts",
        )
        hover_sphere = pv.Sphere(radius=self._handle_radius * 0.6)
        self._hover_actor = self.pl.add_mesh(hover_sphere, color="white", name="hover_highlight")
        self._hover_actor.SetVisibility(False)
        self.pl.add_axes()
        self.pl.set_background("slategray")

    # --- helpers ------------------------------------------------------------
    def _nearest_vertex(self, point) -> int:
        p = np.asarray(point, dtype=np.float64).ravel()[:3]
        return int(np.argmin(np.sum((self.cage.points - p) ** 2, axis=1)))

    def _event_xy(self) -> tuple[int, int]:
        return self.pl.iren.interactor.GetEventPosition()

    def _cursor_ray(self, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
        """World-space ray (origin, direction) through the cursor pixel."""
        ren = self.pl.renderer
        ren.SetDisplayPoint(float(x), float(y), 0.0)
        ren.DisplayToWorld()
        near = np.asarray(ren.GetWorldPoint(), dtype=np.float64)
        ren.SetDisplayPoint(float(x), float(y), 1.0)
        ren.DisplayToWorld()
        far = np.asarray(ren.GetWorldPoint(), dtype=np.float64)
        p0 = near[:3] / near[3]
        p1 = far[:3] / far[3]
        return p0, p1 - p0

    # --- selection / baseline ----------------------------------------------
    def _select(self, idx: int) -> None:
        self.selected = idx
        print(f"[pick] vertex {idx} at {np.round(self.cage.points[idx], 3)}")
        self._build_gizmo(idx)
        self._rebaseline()
        self.pl.render()

    def _rebaseline(self) -> None:
        """Capture the edit baseline (anchor + manual_delta snapshot) and the affected
        vertices/weights. Called on (re)select and whenever radius/soft change."""
        i = self.selected
        if i is None:
            return
        self._anchor = self.cage.points[i].copy()
        self._md0 = self.manual_delta.copy()
        if self.soft_enabled:
            self._aff_idx, self._aff_w = cage.soft_weights(
                self.cage.points, self.cage.points[i], self.soft_radius
            )
        else:
            self._aff_idx = np.array([i], dtype=np.int64)
            self._aff_w = np.array([1.0], dtype=np.float64)
        self._update_soft_viz()

    # --- gizmo --------------------------------------------------------------
    def _remove_gizmo(self) -> None:
        for name in self._giz:
            self.pl.remove_actor(name, render=False)
        self._giz = {}
        self._giz_mode = {}
        self._giz_color = {}

    def _add_handle(self, name: str, mesh, color: str, mode: str, **kw) -> None:
        actor = self.pl.add_mesh(mesh, color=color, name=name, **kw)
        actor.mapper.SetResolveCoincidentTopologyToPolygonOffset()
        addr = actor.GetAddressAsString("")
        self._giz[name] = actor
        self._giz_mode[addr] = mode
        self._giz_color[addr] = color

    def _build_gizmo(self, i: int) -> None:
        """Grabbable handles at the vertex: a red normal arrow (displace along the
        normal) and a green tangent-plane ring (slide across the surface)."""
        anchor = self.cage.points[i].copy()
        n = self.normals[i]
        self._giz_anchor = anchor
        self._remove_gizmo()
        arrow = pv.Arrow(
            start=anchor, direction=n, tip_radius=0.18, shaft_radius=0.07,
            scale=self._axis_len,
        )
        self._add_handle("giz_normal", arrow, "red", "normal")
        disc = pv.Disc(
            center=anchor, inner=self._axis_len * 0.18, outer=self._axis_len * 0.6,
            normal=n, c_res=48,
        )
        self._add_handle("giz_plane", disc, "lime", "tangent", opacity=0.5)
        # Pick list so the handle picker only sees gizmo handles.
        self._handle_picker.InitializePickList()
        for a in self._giz.values():
            self._handle_picker.AddPickList(a)
        self._handle_picker.PickFromListOn()

    def _highlight_handle(self, hovered_actor) -> None:
        for actor in self._giz.values():
            addr = actor.GetAddressAsString("")
            is_hovered = hovered_actor is not None and addr == hovered_actor.GetAddressAsString("")
            actor.prop.color = "yellow" if is_hovered else self._giz_color[addr]

    # --- mouse: press / move / release --------------------------------------
    def _handle_under_cursor(self, x: int, y: int):
        self._handle_picker.Pick(x, y, 0, self.pl.renderer)
        if self._handle_picker.GetCellId() < 0:
            return None
        actor = self._handle_picker.GetActor()
        if actor is None or actor.GetAddressAsString("") not in self._giz_mode:
            return None
        return actor

    def _on_press(self, obj, _event) -> None:
        x, y = self._event_xy()
        actor = self._handle_under_cursor(x, y) if self.selected is not None else None
        if actor is not None:
            # Grab the handle: drag, and suppress the camera for the drag's duration.
            self.mode = self._giz_mode[actor.GetAddressAsString("")]
            self._rebaseline()
            self._dragging = True
            self._suppress_camera(True)
            self._abort(obj, self._press_tag)  # stop the camera style starting a rotate
            return
        # Not on a handle: select the nearest vertex (on press - release is swallowed
        # by pyvista's interactor, so selection must happen here). Dragging empty
        # space still orbits the camera via the trackball style.
        self._mesh_picker.Pick(x, y, 0, self.pl.renderer)
        if self._mesh_picker.GetCellId() >= 0:
            self._select(self._nearest_vertex(self._mesh_picker.GetPickPosition()))

    def _on_move(self, _obj, _event) -> None:
        x, y = self._event_xy()
        if self._dragging:
            self._apply_drag(x, y)
        else:
            self._hover(x, y)

    def _on_release(self, obj, _event) -> None:
        # Only fires for us during a handle drag (the temporary vtkInteractorStyleUser
        # does not swallow release the way pyvista's capture style does).
        if self._dragging:
            self._dragging = False
            self._suppress_camera(False)
            self._abort(obj, self._release_tag)
            self._push_history()  # commit the completed drag as one undo step

    def _apply_drag(self, x: int, y: int) -> None:
        i = self.selected
        ray_o, ray_d = self._cursor_ray(x, y)
        if self.mode == "normal":
            target = cage.closest_point_on_axis(ray_o, ray_d, self._anchor, self.normals[i])
        else:
            target = cage.ray_plane_intersect(ray_o, ray_d, self._anchor, self.normals[i])
        move = target - self._anchor
        self.manual_delta[self._aff_idx] = (
            self._md0[self._aff_idx] + self._aff_w[:, None] * move[None, :]
        )
        self._recompose()
        delta = self.cage.points[i] - self._giz_anchor
        for actor in self._giz.values():
            actor.SetPosition(*delta)
        if self._soft_poly is not None:
            self._soft_poly.points = self.cage.points[self._aff_idx]
        self.pl.render()

    def _hover(self, x: int, y: int) -> None:
        actor = self._handle_under_cursor(x, y) if self.selected is not None else None
        if actor is not None:
            self._highlight_handle(actor)
            self._hover_actor.SetVisibility(False)
            self.pl.render()
            return
        self._highlight_handle(None)
        self._mesh_picker.Pick(x, y, 0, self.pl.renderer)
        if self._mesh_picker.GetCellId() >= 0:
            idx = self._nearest_vertex(self._mesh_picker.GetPickPosition())
            self._hover_actor.SetPosition(*self.cage.points[idx])
            self._hover_actor.SetVisibility(True)
        else:
            self._hover_actor.SetVisibility(False)
        self.pl.render()

    @staticmethod
    def _abort(interactor, tag) -> None:
        """Stop lower-priority observers (the camera style) from also handling this
        event, so grabbing a handle does not tumble the view."""
        if tag is not None:
            cmd = interactor.GetCommand(tag)
            if cmd is not None:
                cmd.SetAbortFlag(1)

    def _suppress_camera(self, on: bool) -> None:
        inter = self.pl.iren.interactor
        if on:
            self._saved_style = inter.GetInteractorStyle()
            inter.SetInteractorStyle(vtk.vtkInteractorStyleUser())
        elif self._saved_style is not None:
            inter.SetInteractorStyle(self._saved_style)
            self._saved_style = None

    # --- soft selection -----------------------------------------------------
    def _update_soft_viz(self) -> None:
        self.pl.remove_actor("soft_region", render=False)
        self._soft_poly = None
        if not self.soft_enabled or self.selected is None or len(self._aff_idx) <= 1:
            return
        self._soft_poly = pv.PolyData(self.cage.points[self._aff_idx])
        self._soft_poly["w"] = self._aff_w
        self.pl.add_mesh(
            self._soft_poly, scalars="w", cmap="plasma", clim=[0.0, 1.0],
            render_points_as_spheres=True, point_size=9, name="soft_region",
            show_scalar_bar=False,
        )

    def _toggle_soft(self) -> None:
        self.soft_enabled = not self.soft_enabled
        print(f"[soft] {'on' if self.soft_enabled else 'off'} radius={self.soft_radius:.3f}")
        if self.selected is not None:
            self._rebaseline()
        self._update_help()
        self.pl.render()

    def _scale_radius(self, factor: float) -> None:
        self.soft_radius *= factor
        print(f"[soft] radius={self.soft_radius:.3f}")
        if self.selected is not None and self.soft_enabled:
            self._rebaseline()
        self._update_help()
        self.pl.render()

    # --- undo / redo --------------------------------------------------------
    def _push_history(self) -> None:
        if np.array_equal(self.manual_delta, self._history[self._hist_index]):
            return  # no net change (e.g. a grab with no move)
        del self._history[self._hist_index + 1:]  # drop any redo branch
        self._history.append(self.manual_delta.copy())
        self._hist_index = len(self._history) - 1

    def _restore_state(self, state: np.ndarray) -> None:
        self.manual_delta = state.copy()
        self._recompose()
        if self.selected is not None:
            self._build_gizmo(self.selected)
            self._rebaseline()
        self.pl.render()

    def _undo(self) -> None:
        if self._hist_index > 0:
            self._hist_index -= 1
            print(f"[undo] state {self._hist_index}/{len(self._history) - 1}")
            self._restore_state(self._history[self._hist_index])

    def _redo(self) -> None:
        if self._hist_index < len(self._history) - 1:
            self._hist_index += 1
            print(f"[redo] state {self._hist_index}/{len(self._history) - 1}")
            self._restore_state(self._history[self._hist_index])

    # --- sliders ------------------------------------------------------------
    def _gizmo_follow(self) -> None:
        """Move the gizmo/soft-region to track the selected vertex after the cage
        geometry changes (slider, undo)."""
        if self.selected is None:
            return
        i = self.selected
        self._anchor = self.cage.points[i].copy()
        delta = self.cage.points[i] - self._giz_anchor
        for actor in self._giz.values():
            actor.SetPosition(*delta)
        if self._soft_poly is not None:
            self._soft_poly.points = self.cage.points[self._aff_idx]

    def _on_push(self, value: float) -> None:
        """Displacement slider: push the whole cage along normals. Layered on top of
        per-vertex edits (manual_delta), so those are preserved (see cage.compose)."""
        self.global_push = float(value)
        self._recompose()
        self._gizmo_follow()
        self.pl.render()

    def _on_opacity(self, value: float) -> None:
        self.cage_actor.prop.opacity = float(value)

    # --- create cage --------------------------------------------------------
    def _create_cage(self) -> None:
        """Duplicate the low-poly asset to <stem>_cage.usd (topology-matched cage)."""
        stem, ext = os.path.splitext(self._low_path)
        out = f"{stem}_cage{ext}"
        shutil.copy(self._low_path, out)
        self._cage_path = out
        print(f"[create-cage] wrote {out}")

    # --- lifecycle ----------------------------------------------------------
    def _update_help(self) -> None:
        soft_label = f"ON r={self.soft_radius:.2f}" if self.soft_enabled else "OFF"
        self.pl.add_text(
            "Left-click a vertex to select. Drag the RED arrow to displace (normal),\n"
            "the GREEN ring to slide (along surface).\n"
            "[o] soft-select   [ [ / ] ] radius   [z] undo  [y] redo  [c] create-cage\n"
            f"Soft: {soft_label}",
            font_size=10,
            name="help",
        )

    def run(self) -> None:
        inter = self.pl.iren.interactor
        # Priority above the camera style so a handle grab can abort the rotate.
        self._press_tag = inter.AddObserver("LeftButtonPressEvent", self._on_press, 10.0)
        inter.AddObserver("MouseMoveEvent", self._on_move, 10.0)
        self._release_tag = inter.AddObserver("LeftButtonReleaseEvent", self._on_release, 10.0)
        self.pl.add_key_event("o", self._toggle_soft)
        self.pl.add_key_event("bracketleft", lambda: self._scale_radius(1 / 1.25))
        self.pl.add_key_event("bracketright", lambda: self._scale_radius(1.25))
        self.pl.add_key_event("z", self._undo)
        self.pl.add_key_event("y", self._redo)
        self.pl.add_key_event("c", self._create_cage)
        self.pl.add_slider_widget(
            self._on_push, [0.0, self._push_max], value=self.global_push,
            title="cage offset", pointa=(0.025, 0.10), pointb=(0.31, 0.10),
            style="modern", interaction_event="always",
        )
        self.pl.add_slider_widget(
            self._on_opacity, [0.0, 1.0], value=0.35,
            title="cage opacity", pointa=(0.69, 0.10), pointb=(0.975, 0.10),
            style="modern", interaction_event="always",
        )
        self._update_help()
        self.pl.show()

    def screenshot(self, path: str) -> None:
        self.pl.show(auto_close=False)
        self.pl.screenshot(path)
