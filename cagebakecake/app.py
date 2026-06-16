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

from . import bake, cage, meshio, theme

BAKE_RESOLUTION = 1024


def _base_name(name: str) -> str:
    """Lowercased prim name with a trailing _lp/_hp stripped - the name-match rule
    (so 'MatBall_lp' and 'MatBall_hp' share the base 'matball')."""
    n = name.lower()
    for suffix in ("_lp", "_hp"):
        if n.endswith(suffix):
            return n[: -len(suffix)]
    return n


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
        # Load each file as a scene: per-prim display parts + a merged mesh (with cached
        # triangulation / UVs) for the cage and bake. One read per file.
        low_scene = meshio.load_scene(low_path, with_uvs=True)
        self.low = low_scene["merged"]
        self.low_parts = low_scene["parts"]
        self._low_ranges = low_scene["ranges"]
        self._cached_low_tris = low_scene["tris"]
        self._cached_low_uvs = low_scene["uvs"]
        # Hard normals stay on the low poly (they author the bake's tangent frame); the
        # cage push / bake rays fire along the skew blend of hard and soft (welded) normals
        # (M8.1 soft normals, M8.2 skew). skew=1 is pure soft - watertight over hard edges -
        # and is the default, so the firing direction matches the pre-skew behaviour.
        self.hard_normals = np.asarray(self.low.point_normals, dtype=np.float64).copy()
        self.soft_normals = cage.soft_vertex_normals(self.low.points, self.hard_normals)
        self.skew = 1.0  # uniform skew value (the slider); 0 = hard, 1 = soft
        # Per-vertex skew weights so skew can be painted per region (default uniform).
        self.skew_map = np.full(len(self.hard_normals), self.skew, dtype=np.float64)
        self.normals = cage.blend_normals(self.hard_normals, self.soft_normals, self.skew_map)
        if high_path:
            high_scene = meshio.load_scene(high_path, with_uvs=False)
            self.high = high_scene["merged"]
            self.high_parts = high_scene["parts"]
            self._cached_high_tris = high_scene["tris"]
        else:
            self.high = None
            self.high_parts = []
            self._cached_high_tris = None
        # The high-poly ray-cast mesh (embree BVH) is the dominant bake cost and does not
        # change while the cage is edited, so build it once and reuse it across bakes.
        # A fresh CageEditor is created when a new high poly is loaded, so this is naturally
        # tied to the current high poly - no explicit invalidation needed.
        self._ray_mesh = None

        # The cage's rest geometry: a topology-matched cage is used directly; a cage with
        # different topology is resampled onto the low poly along its normals so the rest of
        # the editor still has one cage vertex per low vertex (stretch: arbitrary cages).
        if cage_path:
            cage_mesh = meshio.load_mesh(cage_path)
            if len(cage_mesh.points) == len(self.low.points):
                self.base = np.asarray(cage_mesh.points, dtype=np.float64).copy()
            else:
                cage_tris, _ = meshio.load_faces_uvs(cage_path, with_uvs=False)
                print(f"[cage] {len(cage_mesh.points)} cage verts != {len(self.low.points)} "
                      "low verts; resampling the cage onto the low poly")
                self.base = cage.resample_cage(
                    self.low.points, self.normals, cage_mesh.points, cage_tris)
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

        # Display modes. Low and high carry independent material switches (wireframe vs a
        # lit PBR material); the low poly can additionally show the baked normal map so the
        # lighting reacts to baked detail. Toggled from the dock/menu/keys; the cage stays
        # visible in every mode. _click_deselect holds a pending empty-click (release with
        # no drag clears the selection).
        self._low_style = "wireframe"
        self._high_style = "shaded"
        self._high_visible = True
        self._low_wire_on = False   # wireframe (edge) overlay on the shaded low poly
        self._high_wire_on = False  # wireframe (edge) overlay on the shaded high poly
        self._normal_map_on = False
        self._baked_image: np.ndarray | None = None  # last tangent-space normal bake (H,W,3)
        self._baked_ao: np.ndarray | None = None      # last AO bake (H,W,3)
        self._baked_curv: np.ndarray | None = None    # last curvature bake (H,W,3)
        self._baked_miss: np.ndarray | None = None    # last ray-miss feedback map (H,W,3)
        self._baked_uv: np.ndarray | None = None
        self._packed_outputs: dict = {}  # filename -> (H,W,4) packed recipe output
        self._normals_glyph_on = False
        self._click_deselect: tuple[int, int] | None = None
        self._paint_skew = False    # paint mode: left-drag paints skew instead of selecting
        self._paint_value = 0.0     # brush target skew (0 = hard, 1 = soft)
        self._painting = False
        self._bake_size = (BAKE_RESOLUTION, BAKE_RESOLUTION)  # (width, height); set by the dock
        self._supersample = 1   # anti-alias multiple (bake at NxN, average down)
        self._padding = 0       # UV-island edge padding in texels (0 = none)
        self._ao_samples = 64   # hemisphere rays per texel for the AO bake
        # Per-part visibility for the mesh checklist: {("low"|"high", idx): bool}. Name match
        # links a low part and a high part that share a prim name (toggling one toggles both).
        self._part_vis: dict[tuple[str, int], bool] = {}
        for i in range(len(self.low_parts)):
            self._part_vis[("low", i)] = True
        for i in range(len(self.high_parts)):
            self._part_vis[("high", i)] = True
        self._name_match = False
        self._low_actors: dict = {}
        self._high_actors: dict = {}
        self._hl_parts: list = []  # parts amber-highlighted by name-match hover
        # Active theme palette key (e.g. "A-light"); drives the cage/sky viewport colors.
        self._theme_key = theme.palette_key(theme.DEFAULT_DIRECTION, theme.DEFAULT_MOOD)

        # The render surface. Default is a standalone pyvista Plotter (also the headless
        # screenshot path); the Qt front end injects a pyvistaqt.QtInteractor instead, which
        # is API-compatible for everything used here. See cagebakecake/window.py.
        self.pl = plotter if plotter is not None else pv.Plotter(off_screen=off_screen)
        self._handle_picker = vtk.vtkCellPicker()
        self._handle_picker.SetTolerance(0.01)
        self._mesh_picker = vtk.vtkCellPicker()
        self._mesh_picker.SetTolerance(0.005)
        # A dedicated hover picker restricted to the cage actor: hovering happens on every
        # mouse-move, so picking the whole scene (a dense high poly is millions of cells)
        # is the interactive bottleneck. Selection still uses the full-scene picker.
        self._hover_picker = vtk.vtkCellPicker()
        self._hover_picker.SetTolerance(0.01)
        self._hover_state: tuple | None = None  # last hover result, to skip redundant renders
        self._add_actors()
        self._setup_environment()

    # --- geometry -----------------------------------------------------------
    def _recompose(self) -> None:
        self.cage.points = cage.compose(
            self.base, self.normals, self.global_push, self.manual_delta
        )

    def _add_actors(self) -> None:
        # Low and high meshes go through the style helpers so their material switch is one
        # code path for the initial build and later toggles.
        self._apply_high_style()
        self._apply_low_style()
        # Cage actors take their colors from the active theme palette (the cage is the
        # editable star of the view); set_theme_colors recolors them live.
        c = theme.viewport_colors(self._theme_key)
        self.cage_actor = self.pl.add_mesh(
            self.cage, color=c["cage"], opacity=0.35, name="cage", show_edges=False
        )
        self._cage_pts_actor = self.pl.add_mesh(
            self.cage, style="points", color=c["cage_points"], point_size=12,
            render_points_as_spheres=True, name="cage_pts",
        )
        # Draw the points in front of the coincident cage surface the same way the gizmo
        # handles do, so they are not buried in the depth fight with it.
        self._cage_pts_actor.mapper.SetResolveCoincidentTopologyToPolygonOffset()
        self._cage_wire_actor = self.pl.add_mesh(
            self.cage, style="wireframe", color=c["cage_wire"], line_width=1, name="cage_wire"
        )
        self._cage_wire_actor.SetVisibility(False)  # off by default; the translucent surface reads cleaner
        hover_sphere = pv.Sphere(radius=self._handle_radius * 0.6)
        self._hover_actor = self.pl.add_mesh(hover_sphere, color="white", name="hover_highlight")
        self._hover_actor.SetVisibility(False)
        # Hover picks only the cage surface (cheap), not the whole scene.
        self._hover_picker.InitializePickList()
        self._hover_picker.AddPickList(self.cage_actor)
        self._hover_picker.PickFromListOn()
        self.pl.add_axes()
        self._set_sky(c)

    def _set_sky(self, c: dict) -> None:
        """Paint the viewport background as a radial sky: the lighter sky_top glows from
        the center out to the darker sky_bottom at the corners (a soft studio dome),
        rather than a flat fill or a plain top-to-bottom band. ``set_background`` makes
        sky_top the gradient's second color, which radial mode places at the center."""
        self.pl.set_background(c["sky_bottom"], top=c["sky_top"])
        ren = self.pl.renderer
        ren.SetGradientMode(
            vtk.vtkViewport.GradientModes.VTK_GRADIENT_RADIAL_VIEWPORT_FARTHEST_CORNER)
        ren.GradientBackgroundOn()

    def set_theme(self, key: str) -> None:
        """Recolor the viewport to the given palette key (the cage surface/points/
        wireframe and the sky gradient). The math and meshes are untouched - this is
        pure presentation, matching the panel's live re-theming."""
        self._theme_key = key
        c = theme.viewport_colors(key)
        self.cage_actor.prop.color = c["cage"]
        self._cage_pts_actor.prop.color = c["cage_points"]
        self._cage_wire_actor.prop.color = c["cage_wire"]
        self._set_sky(c)
        self.pl.render()

    # --- display modes (low / high material, normal map, cage, normals) -----
    def _remove_actors(self, actors: dict) -> None:
        for key in actors:
            self.pl.remove_actor(key, render=False)

    def _apply_low_style(self) -> None:
        """(Re)build the low-poly part actors for the current style. Each prim is its own
        actor (so the mesh checklist can toggle it). Wireframe is the editing view; shaded
        is a grey PBR material lit by the HDR (so shift-drag lighting reads), optionally
        carrying the baked normal map so the light reacts to baked detail."""
        self._remove_actors(self._low_actors)
        self._low_actors = {}
        for i, (_name, poly) in enumerate(self.low_parts):
            key = f"low::{i}"
            if self._low_style == "wireframe":
                actor = self.pl.add_mesh(
                    poly, style="wireframe", color="white", line_width=1, name=key
                )
            else:
                mesh, normal_tex = self._shaded_part_inputs(i, poly)
                actor = self.pl.add_mesh(
                    mesh, color="lightgray", pbr=True, metallic=0.1, roughness=0.6,
                    smooth_shading=True, name=key,
                )
                if normal_tex is not None:
                    actor.prop.SetNormalTexture(normal_tex)
                actor.prop.SetEdgeVisibility(self._low_wire_on)  # wireframe overlay
            actor.SetVisibility(self._part_vis.get(("low", i), True))
            self._low_actors[key] = actor

    def _apply_high_style(self) -> None:
        """(Re)build the high-poly part actors for the current style; independent of the
        low. Master visibility (_high_visible) ANDs with each part's checklist state."""
        self._remove_actors(self._high_actors)
        self._high_actors = {}
        for i, (_name, poly) in enumerate(self.high_parts):
            key = f"high::{i}"
            if self._high_style == "wireframe":
                actor = self.pl.add_mesh(
                    poly, style="wireframe", color="tan", line_width=1, name=key
                )
            else:
                actor = self.pl.add_mesh(
                    poly, color="tan", pbr=True, metallic=0.15, roughness=0.5,
                    smooth_shading=True, name=key,
                )
                actor.prop.SetEdgeVisibility(self._high_wire_on)  # wireframe overlay
            actor.SetVisibility(self._high_visible and self._part_vis.get(("high", i), True))
            self._high_actors[key] = actor

    def _shaded_part_inputs(self, i: int, poly: pv.PolyData):
        """(mesh, vtkTexture|None) for a shaded low-poly part: the bare part, or - when a
        bake exists and the normal map is on - a triangulated copy carrying that part's
        slice of the baked UVs plus tangents and the normal-map texture."""
        if not (self._normal_map_on and self._baked_image is not None
                and self._baked_uv is not None):
            return poly, None
        _name, start, count = self._low_ranges[i]
        mesh = poly.copy()
        mesh.active_texture_coordinates = self._baked_uv[start:start + count].astype(np.float32)
        mesh = mesh.triangulate()  # vtkPolyDataTangents needs triangles
        self._add_tangents(mesh)
        return mesh, self._make_normal_texture(self._baked_image)

    @staticmethod
    def _add_tangents(mesh: pv.PolyData) -> None:
        """Attach a per-point 'Tangents' array (from the UV gradient) so VTK's PBR shader
        can apply the tangent-space normal map."""
        from vtk.util import numpy_support

        f = vtk.vtkPolyDataTangents()
        f.SetInputData(mesh)
        f.Update()
        arr = f.GetOutput().GetPointData().GetArray("Tangents")
        if arr is not None:
            mesh.point_data["Tangents"] = numpy_support.vtk_to_numpy(arr)

    @staticmethod
    def _make_normal_texture(image: np.ndarray) -> "vtk.vtkTexture":
        """A linear (non-sRGB) VTK texture from the baked normal-map buffer. Rows are
        flipped because texture origin is bottom-left while image row 0 is the top."""
        from vtk.util import numpy_support

        h, w = image.shape[:2]
        flat = np.ascontiguousarray(image[::-1].reshape(-1, image.shape[2]))
        vtk_arr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        img = vtk.vtkImageData()
        img.SetDimensions(w, h, 1)
        img.GetPointData().SetScalars(vtk_arr)
        tex = vtk.vtkTexture()
        tex.SetInputData(img)
        tex.InterpolateOn()
        tex.MipmapOn()
        tex.SetUseSRGBColorSpace(False)
        return tex

    def set_low_style(self, shaded: bool) -> None:
        self._low_style = "shaded" if shaded else "wireframe"
        self._apply_low_style()
        self.pl.render()

    def toggle_low_style(self) -> None:
        self.set_low_style(self._low_style == "wireframe")

    def set_high_style(self, shaded: bool) -> None:
        self._high_style = "shaded" if shaded else "wireframe"
        self._apply_high_style()
        self.pl.render()

    def toggle_high_style(self) -> None:
        self.set_high_style(self._high_style == "wireframe")

    def set_high_visible(self, on: bool) -> None:
        """Show/hide the whole high poly (master toggle; ANDed with each part's checklist
        state). It is opaque and otherwise occludes the cage and low poly."""
        if self.high is None:
            return
        self._high_visible = bool(on)
        for i, key in enumerate(self._high_actors):
            self._high_actors[key].SetVisibility(
                self._high_visible and self._part_vis.get(("high", i), True)
            )
        self.pl.render()

    def set_low_wire(self, on: bool) -> None:
        """Toggle a wireframe (edge) overlay on the shaded low-poly parts."""
        self._low_wire_on = bool(on)
        for actor in self._low_actors.values():
            actor.prop.SetEdgeVisibility(self._low_wire_on)
        self.pl.render()

    def toggle_low_wire(self) -> None:
        self.set_low_wire(not self._low_wire_on)

    def set_high_wire(self, on: bool) -> None:
        """Toggle a wireframe (edge) overlay on the shaded high-poly parts."""
        self._high_wire_on = bool(on)
        for actor in self._high_actors.values():
            actor.prop.SetEdgeVisibility(self._high_wire_on)
        self.pl.render()

    def toggle_high_wire(self) -> None:
        self.set_high_wire(not self._high_wire_on)

    # --- per-mesh checklist + name match ------------------------------------
    def meshes(self) -> list[tuple[str, int, str, bool]]:
        """The mesh checklist: (group, index, label, visible) for every loaded part."""
        out = []
        for group, parts in (("low", self.low_parts), ("high", self.high_parts)):
            for i, (name, _poly) in enumerate(parts):
                out.append((group, i, f"{group}: {name}", self._part_vis.get((group, i), True)))
        return out

    def _part_actor(self, group: str, idx: int):
        return (self._low_actors if group == "low" else self._high_actors).get(f"{group}::{idx}")

    def set_part_visible(self, group: str, idx: int, on: bool) -> None:
        """Show/hide one part (mesh checklist). With name match on, a part with the same
        prim name in the other poly is toggled to match."""
        on = bool(on)
        self._part_vis[(group, idx)] = on
        self._apply_part_visibility(group, idx)
        if self._name_match:
            for g2, i2 in self._matching_parts(group, idx):
                self._part_vis[(g2, i2)] = on
                self._apply_part_visibility(g2, i2)
        self.pl.render()

    def _apply_part_visibility(self, group: str, idx: int) -> None:
        actor = self._part_actor(group, idx)
        if actor is not None:
            vis = self._part_vis.get((group, idx), True)
            if group == "high":
                vis = vis and self._high_visible
            actor.SetVisibility(vis)

    def _matching_parts(self, group: str, idx: int):
        """Parts in the *other* poly whose prim name equals this part's (for name match)."""
        parts = self.low_parts if group == "low" else self.high_parts
        if idx >= len(parts):
            return []
        name = parts[idx][0]
        other_group = "high" if group == "low" else "low"
        other = self.high_parts if group == "low" else self.low_parts
        return [(other_group, j) for j, (n, _p) in enumerate(other) if n == name]

    def set_name_match(self, on: bool) -> None:
        self._name_match = bool(on)

    # --- name-match table (pair low/high parts by base name) ----------------
    def name_pairs(self) -> list[dict]:
        """Rows for the name-match table. Pair each low part to a high part whose base
        name matches (trailing _lp/_hp stripped, case-insensitive); unpaired high parts
        follow as their own rows. Each row is a dict {low, high, low_name, high_name,
        status}, where status is matched / no match (or manual when name-match is off)."""
        rows = []
        used_high: set[int] = set()
        for i, (lname, _p) in enumerate(self.low_parts):
            base = _base_name(lname)
            match = None
            for j, (hname, _hp) in enumerate(self.high_parts):
                if j not in used_high and _base_name(hname) == base:
                    match = j
                    used_high.add(j)
                    break
            rows.append(self._pair_row(i, match))
        for j in range(len(self.high_parts)):
            if j not in used_high:
                rows.append(self._pair_row(None, j))
        return rows

    def _pair_row(self, low_idx: int | None, high_idx: int | None) -> dict:
        lname = self.low_parts[low_idx][0] if low_idx is not None else None
        hname = self.high_parts[high_idx][0] if high_idx is not None else None
        if not self._name_match:
            status = "manual"
        elif lname and hname and _base_name(lname) == _base_name(hname):
            status = "matched"
        else:
            status = "no match"
        return {"low": low_idx, "high": high_idx,
                "low_name": lname, "high_name": hname, "status": status}

    def rename_part(self, group: str, idx: int, name: str) -> None:
        """Rename a loaded part (name-match table edit). Drives the live match status;
        the geometry is untouched."""
        parts = self.low_parts if group == "low" else self.high_parts
        if 0 <= idx < len(parts):
            _old, poly = parts[idx]
            parts[idx] = (name, poly)

    def highlight_parts(self, parts: list[tuple[str, int]]) -> None:
        """Amber-highlight the given mesh parts (name-match hover), restoring whatever
        was highlighted before. Pure presentation - recolors the part actors."""
        self.clear_part_highlight()
        saved = []
        for group, idx in parts:
            actor = self._part_actor(group, idx)
            if actor is not None:
                saved.append((group, idx, actor.prop.color))
                actor.prop.color = theme.MESH_HIGHLIGHT
        self._hl_parts = saved
        if saved:
            self.pl.render()

    def clear_part_highlight(self) -> None:
        for group, idx, col in self._hl_parts:
            actor = self._part_actor(group, idx)
            if actor is not None:
                actor.prop.color = col
        if self._hl_parts:
            self._hl_parts = []
            self.pl.render()

    def set_normal_map(self, on: bool) -> None:
        self._normal_map_on = bool(on)
        if self._low_style == "shaded":
            self._apply_low_style()
        self.pl.render()

    def toggle_normal_map(self) -> None:
        self.set_normal_map(not self._normal_map_on)

    def set_cage_points(self, on: bool) -> None:
        actor = self.pl.actors.get("cage_pts")
        if actor is not None:
            actor.SetVisibility(bool(on))
            self.pl.render()

    def toggle_cage_points(self) -> None:
        actor = self.pl.actors.get("cage_pts")
        if actor is not None:
            self.set_cage_points(not actor.GetVisibility())

    def set_cage_wire(self, on: bool) -> None:
        actor = self.pl.actors.get("cage_wire")
        if actor is not None:
            actor.SetVisibility(bool(on))
            self.pl.render()

    def toggle_cage_wire(self) -> None:
        actor = self.pl.actors.get("cage_wire")
        if actor is not None:
            self.set_cage_wire(not actor.GetVisibility())

    def set_low_normals(self, on: bool) -> None:
        """Show/hide little glyphs along the low poly's vertex normals for inspection."""
        self.pl.remove_actor("low_normals", render=False)
        self._normals_glyph_on = bool(on)
        if self._normals_glyph_on:
            glyphs = self.low.glyph(
                orient="Normals", scale=False, factor=self._diag * 0.04, geom=pv.Arrow()
            )
            self.pl.add_mesh(glyphs, color="yellow", name="low_normals", lighting=False)
        self.pl.render()

    def toggle_low_normals(self) -> None:
        self.set_low_normals(not self._normals_glyph_on)

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

    def _deselect(self) -> None:
        """Clear the current selection and remove its gizmo (left-click on empty space)."""
        if self.selected is None:
            return
        self.selected = None
        self._remove_gizmo()
        self._hover_actor.SetVisibility(False)
        self._update_soft_viz()
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
        # render=False: building the gizmo adds three handles; without this each add_mesh
        # re-renders the whole (possibly multi-million-point) scene. _select renders once
        # at the end instead, so a selection costs one frame, not four.
        actor = self.pl.add_mesh(mesh, color=color, name=name, render=False, **kw)
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
        free = pv.Cube(center=anchor, x_length=self._axis_len * 0.18,
                       y_length=self._axis_len * 0.18, z_length=self._axis_len * 0.18)
        self._add_handle("giz_free", free, "deepskyblue", "free")  # drag in the view plane
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
        if self._paint_skew:
            # Paint mode: left-drag paints the brush skew onto the mesh under the cursor.
            self._mesh_picker.Pick(x, y, 0, self.pl.renderer)
            if self._mesh_picker.GetCellId() >= 0:
                self.paint_skew_at(self._mesh_picker.GetPickPosition(), self._paint_value)
                self._painting = True
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
            self._click_deselect = None
        else:
            # Empty space: a click here (no drag) deselects; remember the press so the
            # release can tell a click from an orbit (cancelled on move below).
            self._click_deselect = (x, y)

    def _on_move(self, _obj, _event) -> None:
        x, y = self._event_xy()
        if self._click_deselect is not None:
            cx, cy = self._click_deselect
            if abs(x - cx) + abs(y - cy) > 4:
                self._click_deselect = None  # it became an orbit, not a click
        if self._painting:
            self._mesh_picker.Pick(x, y, 0, self.pl.renderer)
            if self._mesh_picker.GetCellId() >= 0:
                self.paint_skew_at(self._mesh_picker.GetPickPosition(), self._paint_value)
        elif self._env_rotating:
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
        if self._painting:
            self._painting = False
            self._suppress_camera(False)
            self._abort(obj, self._release_tag)
            return
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
            return
        if self._click_deselect is not None:
            # A left click on empty space (press + release, no orbit) clears the selection.
            self._click_deselect = None
            self._deselect()

    def _apply_drag(self, x: int, y: int) -> None:
        i = self.selected
        ray_o, ray_d = self._cursor_ray(x, y)
        if self.mode == "normal":
            target = cage.closest_point_on_axis(ray_o, ray_d, self._anchor, self.normals[i])
        elif self.mode == "free":
            # Free 3-axis: drag in the plane facing the camera through the anchor.
            view = np.asarray(self.pl.camera.direction, dtype=np.float64)
            target = cage.ray_plane_intersect(ray_o, ray_d, self._anchor, view)
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
        # Re-render only when the hover result actually changes - a full render of a dense
        # scene on every mouse-move is the interactive bottleneck (see docs/baking.md perf).
        handle = self._handle_under_cursor(x, y) if self.selected is not None else None
        if handle is not None:
            addr = handle.GetAddressAsString("")
            if self._hover_state != ("handle", addr):
                self._highlight_handle(handle)
                self._hover_actor.SetVisibility(False)
                self._hover_state = ("handle", addr)
                self.pl.render()
            return
        # Nearest cage vertex under the cursor (cage-only pick = cheap).
        self._hover_picker.Pick(x, y, 0, self.pl.renderer)
        idx = (self._nearest_vertex(self._hover_picker.GetPickPosition())
               if self._hover_picker.GetCellId() >= 0 else None)
        if self._hover_state == ("vertex", idx):
            return  # unchanged -> skip the re-render
        self._highlight_handle(None)
        if idx is not None:
            self._hover_actor.SetPosition(*self.cage.points[idx])
            self._hover_actor.SetVisibility(True)
        else:
            self._hover_actor.SetVisibility(False)
        self._hover_state = ("vertex", idx)
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

    def _reblend_skew(self) -> None:
        """Recompute firing normals from the skew map and recompose; keep the gizmo on."""
        self.normals = cage.blend_normals(self.hard_normals, self.soft_normals, self.skew_map)
        self._recompose()
        if self.selected is not None:
            self._build_gizmo(self.selected)
            self._rebaseline()
        else:
            self._gizmo_follow()
        self.pl.render()

    def set_skew(self, value: float) -> None:
        """M8.2 skew (uniform): set every vertex's skew, blending the cage push / bake ray
        direction between the hard normals (0) and the soft welded normals (1)."""
        self.skew = float(np.clip(value, 0.0, 1.0))
        self.skew_map[:] = self.skew
        self._reblend_skew()

    def paint_skew_at(self, point, value: float, radius: float | None = None) -> None:
        """Paint skew into vertices near `point` with a smooth falloff (stretch: paintable
        skew). value in [0,1]; the brush blends each affected vertex toward it by weight."""
        radius = self.soft_radius if radius is None else float(radius)
        idx, w = cage.soft_weights(self.cage.points, np.asarray(point, dtype=np.float64), radius)
        if len(idx) == 0:
            return
        value = float(np.clip(value, 0.0, 1.0))
        self.skew_map[idx] = np.clip(self.skew_map[idx] * (1.0 - w) + value * w, 0.0, 1.0)
        self._reblend_skew()

    def set_paint_skew(self, on: bool) -> None:
        """Toggle skew paint mode (left-drag on the mesh paints the brush value)."""
        self._paint_skew = bool(on)

    def set_paint_value(self, value: float) -> None:
        self._paint_value = float(np.clip(value, 0.0, 1.0))

    # --- create cage --------------------------------------------------------
    def _create_cage(self) -> None:
        """Duplicate the low-poly asset to <stem>_cage.usd (topology-matched cage)."""
        stem, ext = os.path.splitext(self._low_path)
        out = f"{stem}_cage{ext}"
        shutil.copy(self._low_path, out)
        self._cage_path = out
        print(f"[create-cage] wrote {out}")

    def save_cage(self, out_path: str | None = None) -> str:
        """Write the *edited* cage (global push + every per-vertex/skew edit) to USD.

        Unlike `_create_cage`, which copies the untouched source low poly, this saves the
        cage geometry the artist actually authored. `out_path` defaults to
        <low-stem>_cage_edited.usd next to the low poly. Returns the path written."""
        if out_path is None:
            stem, _ext = os.path.splitext(self._low_path)
            out_path = f"{stem}_cage_edited.usd"
        meshio.save_mesh(out_path, self.cage.points, self.cage.faces)
        print(f"[save-cage] wrote {out_path}")
        return out_path

    # --- view toggles -------------------------------------------------------
    def _toggle_high(self) -> None:
        """Show/hide the high poly so it stops occluding the cage and low poly. Tracked so
        the visibility survives a material-switch rebuild of the actor."""
        self.set_high_visible(not self._high_visible)

    # --- bake (M7.4) --------------------------------------------------------
    def set_bake_size(self, width: int, height: int) -> None:
        """Set the baked normal-map size (the dock width/height dropdowns drive this)."""
        self._bake_size = (int(width), int(height))

    def set_supersample(self, ss: int) -> None:
        """Anti-alias multiple: bake at ss x the size and average down (dock dropdown)."""
        self._supersample = max(1, int(ss))

    def set_padding(self, px: int) -> None:
        """UV-island edge padding in texels bled into the background (dock dropdown)."""
        self._padding = max(0, int(px))

    def set_ao_samples(self, n: int) -> None:
        """Hemisphere rays per texel for the AO bake (dock dropdown)."""
        self._ao_samples = max(1, int(n))

    def _get_ray_mesh(self):
        """The cached high-poly ray mesh (embree BVH), built on first use. Reused by every
        bake so only the first one pays the BVH build."""
        if self._ray_mesh is None and self.high is not None:
            self._ray_mesh = bake.make_ray_mesh(self.high.points, self._cached_high_tris)
        return self._ray_mesh

    def _bake_ao(self, out_path: str | None = None, progress=None, should_cancel=None,
                 write: bool = True) -> None:
        """Bake an ambient-occlusion map of the high poly onto the low poly's UVs and
        write it next to the low poly (or to `out_path`). `write=False` bakes to memory
        only (used by recipe baking, where the packed outputs are the deliverables)."""
        if self.high is None:
            self._bake_status("AO needs a high poly (pass --high).")
            self.pl.render()
            return
        if self._cached_low_uvs is None:
            self._bake_status("AO failed: the low poly has no UVs.")
            self.pl.render()
            return
        w, h = self._bake_size
        out = out_path or (os.path.splitext(os.path.basename(self._low_path))[0] + "_ao.png"
                           if write else None)
        self._bake_status(f"Baking AO {w}x{h} ({self._ao_samples} rays/texel)...")
        self.pl.render()
        image = bake.bake_ao(
            self.low.points, self._cached_low_tris, self.hard_normals, self._cached_low_uvs,
            self.high.points, self._cached_high_tris, resolution=(w, h),
            samples=self._ao_samples, padding=self._padding, out_path=out,
            progress=progress or (lambda m: print(f"[ao] {m}")),
            should_cancel=should_cancel, ray_mesh=self._get_ray_mesh(),
        )
        if image is not None:
            self._baked_ao = image
        done = "AO cancelled." if image is None else (f"Baked AO -> {out}" if out else "Baked AO.")
        self._bake_status(done)
        self.pl.render()

    def _bake_curvature(self, out_path: str | None = None, write: bool = True) -> None:
        """Derive a curvature map from the last baked normal map and write it out.
        `write=False` derives it in memory only (recipe baking)."""
        if self._baked_image is None:
            self._bake_status("Curvature needs a normal-map bake first (press Bake).")
            self.pl.render()
            return
        out = out_path or (os.path.splitext(os.path.basename(self._low_path))[0] + "_curv.png"
                           if write else None)
        curv = bake.curvature_from_normal_map(self._baked_image)
        if out:
            bake._write_png(out, curv)
        self._baked_curv = curv
        self._bake_status(f"Baked curvature -> {out}" if out else "Baked curvature.")
        self.pl.render()

    def _bake(self, out_path: str | None = None, resolution=None,
              progress=None, should_cancel=None, write: bool = True) -> None:
        """Bake a tangent-space normal map from the high poly onto the low poly using the
        current cage as the per-vertex ray bound, then show it lit on the shaded low poly
        (the cage stays visible). `out_path` overrides the default `<low>_normal.png`
        (File > Export); `resolution` is an int or (width, height), default `_bake_size`.
        `write=False` bakes to memory only (recipe baking). Use the Normal map /
        Low-poly-shaded toggles to compare before and after."""
        if self.high is None:
            self._bake_status("Bake needs a high poly (pass --high).")
            self.pl.render()
            return
        # Triangulation / UVs were cached at load (merged across all prims).
        low_tris, low_uvs = self._cached_low_tris, self._cached_low_uvs
        high_tris = self._cached_high_tris
        if low_uvs is None:
            self._bake_status("Bake failed: the low poly has no UVs.")
            self.pl.render()
            return

        res = resolution if resolution is not None else self._bake_size
        w, h = (res, res) if isinstance(res, int) else (int(res[0]), int(res[1]))
        out = out_path or (os.path.splitext(os.path.basename(self._low_path))[0] + "_normal.png"
                           if write else None)
        self._bake_status(f"Baking {w}x{h} (this can take a while)...")
        self.pl.render()
        result = bake.bake(
            self.low.points, low_tris, self.hard_normals, low_uvs,
            self.cage.points, self.high.points, high_tris,
            np.asarray(self.high.point_normals, dtype=np.float64),
            resolution=(w, h), out_path=out,
            progress=progress or (lambda m: print(f"[bake] {m}")),
            firing_normals=self.normals,  # skew-blended ray direction (M8.2)
            supersample=self._supersample, padding=self._padding,
            should_cancel=should_cancel, return_miss=True,
            ray_mesh=self._get_ray_mesh(),  # cached embree BVH (perf)
        )
        if result is None:
            self._bake_status("Bake cancelled.")
            self.pl.render()
            return
        image, self._baked_miss = result  # miss map = ray-miss / projection feedback
        # Per-point UVs for the lit preview (last corner wins at seams - fine for preview).
        pp_uv = np.zeros((self.low.n_points, 2), dtype=np.float32)
        pp_uv[low_tris.reshape(-1)] = low_uvs.reshape(-1, 2).astype(np.float32)
        self._baked_image = image
        self._baked_uv = pp_uv
        # Show the result lit on the low poly without hiding the cage: shaded + normal map.
        self._normal_map_on = True
        self.set_low_style(True)
        self._bake_status(f"Baked -> {out}   [n] normal map  [l] low-poly shading"
                          if out else "Baked.   [n] normal map  [l] low-poly shading")
        self.pl.render()

    def bake_recipe(self, rec, out_dir: str | None = None,
                    progress=None, should_cancel=None) -> list[str] | None:
        """Bake every map type a recipe needs, then pack them into its output PNGs.

        Bakes each supported kind once (normal -> AO -> curvature, reusing the single
        bakes so the cached BVH is shared), assembles a {map id -> array} table for the
        bakeable kinds, and writes one PNG per output via bake.pack_outputs. Map kinds
        with no bake yet (position/cavity/thickness/height, and object-space normals)
        pack as empty channels. Returns the written paths, or None if cancelled.
        """
        notify = progress or (lambda _m: None)
        kinds = {m.kind for m in rec.bake_maps}
        cancelled = lambda: bool(should_cancel and should_cancel())

        if "normal" in kinds:
            self._bake(progress=progress, should_cancel=should_cancel, write=False)
            if cancelled():
                return None
        if "ao" in kinds:
            self._bake_ao(progress=progress, should_cancel=should_cancel, write=False)
            if cancelled():
                return None
        if "curv" in kinds and self._baked_image is not None:
            self._bake_curvature(write=False)

        # Map each recipe bake map to its baked buffer (only bakeable kinds resolve;
        # object-space normals are not produced by the tangent-space bake).
        by_kind = {"normal": self._baked_image, "ao": self._baked_ao,
                   "curv": self._baked_curv}
        baked = {}
        for m in rec.bake_maps:
            arr = by_kind.get(m.kind)
            if m.kind == "normal" and m.space == "object":
                arr = None
            if arr is not None:
                baked[m.id] = arr

        lp_name = os.path.splitext(os.path.basename(self._low_path))[0]
        files = bake.pack_outputs(baked, rec, lp_name)
        out_dir = out_dir or os.path.dirname(self._low_path) or "."
        written = []
        for fname, img in files.items():
            path = os.path.join(out_dir, fname)
            bake._write_png(path, img)
            self._packed_outputs[fname] = img
            written.append(path)
            notify(f"wrote {path}")
        self._bake_status(f"Recipe baked -> {len(written)} texture(s)")
        self.pl.render()
        return written

    def _bake_status(self, msg: str) -> None:
        if msg:
            print(f"[bake] {msg}")
        self.pl.add_text(
            msg, position="lower_right", font_size=9, color="yellow", name="bake_status"
        )

    def baked_maps(self) -> list[tuple[str, np.ndarray]]:
        """The baked maps currently in memory, as (name, RGB image) - feeds the 2D bake
        preview. Empty until something is baked; cleared when a new mesh is loaded.
        Packed recipe outputs are listed after the raw per-type maps."""
        maps = []
        if self._baked_image is not None:
            maps.append(("Normal", self._baked_image))
        if self._baked_ao is not None:
            maps.append(("AO", self._baked_ao))
        if self._baked_curv is not None:
            maps.append(("Curvature", self._baked_curv))
        if self._baked_miss is not None:
            maps.append(("Ray miss", self._baked_miss))
        for fname, img in self._packed_outputs.items():
            maps.append((fname, img))
        return maps

    # --- lifecycle ----------------------------------------------------------
    def _update_help(self) -> None:
        soft_label = f"ON r={self.soft_radius:.2f}" if self.soft_enabled else "OFF"
        self.pl.add_text(
            "Left-click a vertex to select (click empty space / [d] to deselect).\n"
            "Drag RED arrow = displace (normal), GREEN ring = slide, BLUE cube = free.\n"
            "[o] soft-select  [ [ / ] ] radius  [z] undo  [y] redo  [c] create-cage\n"
            "[x] reset point  [X] reset cage  [b] bake  [h] hide high\n"
            "[l] low shading  [L] high shading  [n] normal map  [v] LP normals\n"
            "[k] cage points  [j] cage wireframe   shift-drag = rotate HDR lighting\n"
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
        # Display toggles (chosen to avoid VTK built-ins w/s/r/p/e/q/f).
        self.pl.add_key_event("l", self.toggle_low_style)
        self.pl.add_key_event("L", self.toggle_high_style)
        self.pl.add_key_event("n", self.toggle_normal_map)
        self.pl.add_key_event("k", self.toggle_cage_points)
        self.pl.add_key_event("j", self.toggle_cage_wire)
        self.pl.add_key_event("v", self.toggle_low_normals)
        self.pl.add_key_event("d", self._deselect)

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
