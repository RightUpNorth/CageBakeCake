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

import math
import os
import shutil

import numpy as np
import pyvista as pv
import vtk

from . import bake, cage, meshio

BAKE_RESOLUTION = 1024


class CageEditor:
    def __init__(
        self,
        low_path: str,
        high_path: str | None = None,
        cage_path: str | None = None,
        hdr_path: str | None = None,
        global_push: float | None = None,
        off_screen: bool = False,
        plotter: "pv.Plotter | None" = None,
    ):
        self._low_path = low_path
        self._high_path = high_path
        self._cage_path = cage_path
        self._hdr_path = hdr_path
        self._preview_on = False
        self.low = meshio.load_mesh(low_path)
        # Hard normals stay on the low poly (they author the bake); the cage push uses
        # soft (welded) normals so the shell is watertight over hard edges. (M8.1)
        self.hard_normals = np.asarray(self.low.point_normals, dtype=np.float64).copy()
        self.normals = cage.soft_vertex_normals(self.low.points, self.hard_normals)
        self.high = meshio.load_mesh(high_path) if high_path else None

        # The cage's rest geometry: a loaded cage (topology-checked) or the low poly.
        if cage_path:
            cage_mesh = meshio.load_mesh(cage_path)
            cage.validate_correspondence(self.low.points, cage_mesh.points)
            self.base = np.asarray(cage_mesh.points, dtype=np.float64).copy()
        else:
            self.base = np.asarray(self.low.points, dtype=np.float64).copy()
        # Default the cage offset to a fraction of the mesh size so it is sensible at any
        # scale (an absolute default bakes empty on small meshes / overshoots on large);
        # an explicit global_push is still taken as absolute world units.
        diag0 = float(np.linalg.norm(np.ptp(self.base, axis=0)))
        self.global_push = diag0 * 0.03 if global_push is None else float(global_push)
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

        # HDR environment rotation (shift-drag).
        self._env_rotating = False
        self._env_yaw = 0.0
        self._env_yaw0 = 0.0
        self._env_start_x = 0

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
        self._diag = diag
        self._handle_radius = diag * 0.02
        self._axis_len = diag * 0.14
        self.soft_radius = diag * 0.1
        self._push_max = diag * 0.3

        # The render surface. Default is a standalone pyvista Plotter (also the headless
        # screenshot path); the Qt front end injects a pyvistaqt.QtInteractor instead, which
        # is API-compatible for everything used here. See cagebakecake/window.py.
        self.pl = plotter if plotter is not None else pv.Plotter(off_screen=off_screen)
        self._handle_picker = vtk.vtkCellPicker()
        self._handle_picker.SetTolerance(0.01)
        self._mesh_picker = vtk.vtkCellPicker()
        self._mesh_picker.SetTolerance(0.005)
        self._add_actors()
        self._setup_environment()

    # --- geometry -----------------------------------------------------------
    def _recompose(self) -> None:
        self.cage.points = cage.compose(
            self.base, self.normals, self.global_push, self.manual_delta
        )

    def _add_actors(self) -> None:
        # High poly: opaque PBR reference lit by the HDR environment (M5/M6).
        if self.high is not None:
            self.pl.add_mesh(
                self.high, color="tan", pbr=True, metallic=0.15, roughness=0.5,
                smooth_shading=True, name="high",
            )
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
        if obj.GetShiftKey():
            # Shift-drag rotates the HDR environment (moves the lighting).
            self._env_rotating = True
            self._env_start_x = x
            self._env_yaw0 = self._env_yaw
            self._suppress_camera(True)
            self._abort(obj, self._press_tag)
            return
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
        if self._env_rotating:
            self._env_yaw = self._env_yaw0 + (x - self._env_start_x) * 0.01
            self._apply_env_rotation()
            self.pl.render()
        elif self._dragging:
            self._apply_drag(x, y)
        else:
            self._hover(x, y)

    def _on_release(self, obj, _event) -> None:
        # Only fires for us during a handle / environment drag (the temporary
        # vtkInteractorStyleUser does not swallow release like pyvista's capture style).
        if self._env_rotating:
            self._env_rotating = False
            self._suppress_camera(False)
            self._abort(obj, self._release_tag)
            return
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
        self.set_soft_radius(self.soft_radius * factor)

    def set_soft_enabled(self, on: bool) -> None:
        """Set soft-select on/off (the Qt checkbox drives this; [o] toggles it)."""
        if bool(on) != self.soft_enabled:
            self._toggle_soft()

    def set_soft_radius(self, radius: float) -> None:
        """Set the soft-select falloff radius to an absolute value (Qt radius slider)."""
        self.soft_radius = float(radius)
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

    def _reset_cage(self) -> None:
        """Clear every per-vertex edit, returning the cage to its uniform push (the
        offset slider is untouched). Undoable as a single step."""
        if not self.manual_delta.any():
            return
        self.manual_delta[:] = 0.0
        self._recompose()
        self._push_history()
        if self.selected is not None:
            self._build_gizmo(self.selected)
            self._rebaseline()
        self.pl.render()
        print("[reset] cleared all cage edits")

    def _reset_selected(self) -> None:
        """Clear the selected vertex's edit, returning just that point to the push."""
        if self.selected is None or not self.manual_delta[self.selected].any():
            return
        self.manual_delta[self.selected] = 0.0
        self._recompose()
        self._push_history()
        self._build_gizmo(self.selected)
        self._rebaseline()
        self.pl.render()
        print(f"[reset] cleared vertex {self.selected}")

    # --- environment / lighting (M5/M6) -------------------------------------
    @staticmethod
    def _procedural_sky() -> pv.Texture:
        """A soft equirectangular sky (cool top, warm ground, one broad sun) so PBR
        has image-based lighting without needing an external HDR."""
        h, w = 256, 512
        v = np.linspace(1.0, 0.0, h)[:, None, None]
        top = np.array([0.45, 0.62, 0.95])
        bottom = np.array([0.35, 0.30, 0.28])
        grad = bottom + (top - bottom) * v  # (h, 1, 3)
        yy, xx = np.mgrid[0:h, 0:w]
        sun = np.exp(-((xx - w * 0.65) ** 2) / (2 * 60.0**2)) * np.exp(
            -((yy - h * 0.28) ** 2) / (2 * 45.0**2)
        )
        img = grad + sun[..., None] * np.array([1.2, 1.1, 0.9])
        return pv.Texture((np.clip(img, 0.0, 1.0) * 255).astype(np.uint8))

    def _load_hdr(self, path: str) -> pv.Texture:
        import imageio.v3 as iio

        img = np.asarray(iio.imread(path))
        if img.dtype != np.uint8:  # HDR float -> tonemap to 8-bit for the texture
            img = np.clip(img / (img.max() or 1.0), 0.0, 1.0)
            img = (img * 255).astype(np.uint8)
        return pv.Texture(img[..., :3])

    def _setup_environment(self) -> None:
        # HDR / procedural sky gives ambient image-based lighting + reflections.
        try:
            tex = self._load_hdr(self._hdr_path) if self._hdr_path else self._procedural_sky()
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail to open
            print(f"[hdr] could not load {self._hdr_path}: {exc}; using procedural sky")
            tex = self._procedural_sky()
        self.pl.set_environment_texture(tex, show_background=False)
        # VTK bakes the IBL once and will not re-orient it live, so a movable key
        # light provides the directional "sun" that shift-drag orbits.
        self._key_light = pv.Light(light_type="scene light", intensity=0.8)
        self.pl.add_light(self._key_light)
        self._env_center = np.asarray(self.cage.center, dtype=np.float64)
        self._apply_env_rotation()

    def _apply_env_rotation(self) -> None:
        """Orbit the key light about the world-up (Z) axis - shift-drag moves the
        lighting direction across the high poly."""
        el = math.radians(35.0)
        az = self._env_yaw
        offset = self._diag * 2.0 * np.array(
            [math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)]
        )
        self._key_light.position = tuple(self._env_center + offset)
        self._key_light.focal_point = tuple(self._env_center)

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

    # --- view toggles -------------------------------------------------------
    def _toggle_high(self) -> None:
        """Show/hide the opaque high poly so it stops occluding the cage and low poly."""
        if self.high is None or "high" not in self.pl.actors:
            return
        actor = self.pl.actors["high"]
        actor.SetVisibility(not actor.GetVisibility())
        self.pl.render()

    # --- bake (M7.4) --------------------------------------------------------
    def _bake(self, out_path: str | None = None) -> None:
        """Bake a tangent-space normal map from the high poly onto the low poly using
        the current cage as the per-vertex ray bound, then preview it on the low poly.
        Pressing the key again leaves the preview and returns to editing. `out_path`
        overrides the default `<low>_normal.png` (used by File > Export Normal Map)."""
        if self._preview_on and out_path is None:
            self._hide_preview()
            return
        self._preview_on = False
        if self.high is None:
            self._bake_status("Bake needs a high poly (pass --high).")
            self.pl.render()
            return
        try:
            low_tris, low_uvs = meshio.load_faces_uvs(self._low_path)
            if low_uvs is None:
                self._bake_status("Bake failed: the low poly has no UVs.")
                self.pl.render()
                return
            high_tris, _ = meshio.load_faces_uvs(self._high_path, with_uvs=False)
        except Exception as exc:  # noqa: BLE001 - surface the error, don't crash the app
            self._bake_status(f"Bake failed to read meshes: {exc}")
            self.pl.render()
            return

        out = out_path or (os.path.splitext(os.path.basename(self._low_path))[0] + "_normal.png")
        self._bake_status(f"Baking {BAKE_RESOLUTION}x{BAKE_RESOLUTION} (this can take a while)...")
        self.pl.render()
        image = bake.bake(
            self.low.points, low_tris, self.normals, low_uvs,
            self.cage.points, self.high.points, high_tris,
            np.asarray(self.high.point_normals, dtype=np.float64),
            resolution=BAKE_RESOLUTION, out_path=out,
            progress=lambda m: print(f"[bake] {m}"),
        )
        # Per-point UVs for the preview (last corner wins at seams - fine for preview).
        pp_uv = np.zeros((self.low.n_points, 2), dtype=np.float32)
        pp_uv[low_tris.reshape(-1)] = low_uvs.reshape(-1, 2).astype(np.float32)
        self._show_bake_preview(image, pp_uv)
        self._bake_status(f"Baked -> {out}   [b] back to editing")
        self.pl.render()

    def _show_bake_preview(self, image: np.ndarray, pp_uv: np.ndarray) -> None:
        preview = self.low.copy()
        preview.active_texture_coordinates = pp_uv
        self.pl.add_mesh(
            preview, texture=pv.Texture(image), name="bake_preview", lighting=False,
        )
        # Hide the editing actors so the textured low poly is the only thing shown.
        for nm in ("high", "low", "cage", "cage_pts"):
            if nm in self.pl.actors:
                self.pl.actors[nm].SetVisibility(False)
        self._preview_on = True

    def _hide_preview(self) -> None:
        if "bake_preview" in self.pl.actors:
            self.pl.remove_actor("bake_preview")
        for nm in ("high", "low", "cage", "cage_pts"):
            if nm in self.pl.actors:
                self.pl.actors[nm].SetVisibility(True)
        self._bake_status("")
        self._preview_on = False
        self.pl.render()

    def _bake_status(self, msg: str) -> None:
        if msg:
            print(f"[bake] {msg}")
        self.pl.add_text(
            msg, position="lower_right", font_size=9, color="yellow", name="bake_status"
        )

    # --- lifecycle ----------------------------------------------------------
    def _update_help(self) -> None:
        soft_label = f"ON r={self.soft_radius:.2f}" if self.soft_enabled else "OFF"
        self.pl.add_text(
            "Left-click a vertex to select. Drag the RED arrow to displace (normal),\n"
            "the GREEN ring to slide (along surface).\n"
            "[o] soft-select   [ [ / ] ] radius   [z] undo  [y] redo  [c] create-cage\n"
            "[x] reset point   [X] reset cage   [b] bake (toggles preview)   [h] hide high\n"
            "shift-drag = rotate the HDR lighting\n"
            f"Soft: {soft_label}",
            font_size=10,
            name="help",
        )

    def attach_interaction(self) -> None:
        """Wire the viewport mouse/keyboard interaction onto the plotter's interactor.

        Shared by the standalone Plotter path (`run`) and the Qt front end, which drives
        sliders/buttons from its own widgets but still wants the in-viewport picking,
        gizmo drag, shift-drag lighting, and keyboard shortcuts.
        """
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
        self.pl.add_key_event("b", self._bake)
        self.pl.add_key_event("h", self._toggle_high)
        self.pl.add_key_event("x", self._reset_selected)
        self.pl.add_key_event("X", self._reset_cage)

    def run(self) -> None:
        self.attach_interaction()
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
