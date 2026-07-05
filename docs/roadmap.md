# Roadmap

**Status: milestones 1-8 are all implemented, plus every cross-cutting stretch
goal.** The app loads meshes, edits the cage, shades and lights the high poly,
bakes and packs maps, and persists projects. What remains is polish and a few
experimental features that are in the codebase but not production-ready (see
[Beyond the milestones](#beyond-the-milestones)). Each milestone below keeps its
original plan text as a record and carries a status line; the per-milestone docs
have the fuller "Status" notes.

Milestones were ordered **riskiest first**. Milestone 1 was the only genuinely
uncertain piece; everything after it was standard PyVista wiring over the headless
math.

## Milestone 1 - Pick, gizmo, single-vertex update

Detail and phases: [milestone-1-pick-gizmo.md](milestones/milestone-1-pick-gizmo.md)

**Status: done.** Pick + normal-constrained gizmo (with tangent and free-3-axis
handles as landed stretch goals).

The core interaction loop and the one real unknown, so it is built and verified
first. The first task is to confirm which PyVista primitive reaches the behavior
before assuming raw VTK:

- `enable_point_picking` / `enable_surface_point_picking` to select a cage vertex.
- Oriented handle, simplest first: `add_line_widget` along the normal, else
  `add_sphere_widget` + `project_onto_normal`, else raw `vtkAxesTransformWidget`.
- On drag, write the new position into the cage `PolyData` and re-render.

Default motion: normal-constrained push. Free 3-axis is a stretch toggle.

## Milestone 2 - Load the three meshes

Detail and phases: [milestone-2-load-meshes.md](milestones/milestone-2-load-meshes.md)

**Status: done.** USD is the runtime format (`meshio.load_scene`); FBX/OBJ convert
via Blender offline.

`meshio.load_mesh` for low/cage/high; validate cage-to-low correspondence and error
clearly on mismatch; register three distinctly styled actors.

## Milestone 3 - Displacement slider

Detail and phases: [milestone-3-displacement-slider.md](milestones/milestone-3-displacement-slider.md)

**Status: done.**

`add_slider_widget` -> recompute `base + normal * value + manual_delta` -> update
cage points. Layered so it does not wipe per-vertex edits.

## Milestone 4 - Transparency slider

Detail and phases: [milestone-4-transparency-slider.md](milestones/milestone-4-transparency-slider.md)

**Status: done.**

`add_slider_widget` -> set the cage actor's `opacity`.

## Milestone 5 - Simple shader

Detail and phases: [milestone-5-shader.md](milestones/milestone-5-shader.md)

**Status: done.**

PBR on the high poly (`pbr=True`, metallic/roughness, `smooth_shading=True`).
Metallic/roughness sliders optional.

## Milestone 6 - HDR environment + shift-drag rotate

Detail and phases: [milestone-6-hdr-lighting.md](milestones/milestone-6-hdr-lighting.md)

**Status: done** (with one deviation, noted in the milestone doc).

`set_environment_texture(hdr)` for lighting and reflections; shift-drag observer
accumulates a yaw angle to rotate the HDR; fall back to a 3-point rig with no HDR.

## Milestone 7 - Bake button (heaviest)

Detail and phases: [milestone-7-bake.md](milestones/milestone-7-bake.md)

**Status: done** (phases 7.1-7.4; both follow-ups resolved). Extends well past the
MVP: object-space normal, AO, curvature, height, position and thickness maps, plus
recipe-driven channel packing.

`bake.py`: rasterize low-poly UVs, cast surface -> cage -> high rays via trimesh,
encode the high-poly normal into tangent space, write a PNG, preview on the low
poly. Requires UVs. MVP is a tangent-space normal map only.

## Milestone 8 - Hard/soft normals: watertight cage + skew

Detail and phases: [milestone-8-normals-skew.md](milestones/milestone-8-normals-skew.md)

**Status: done.** Both phases landed: soft (welded) cage normals and the
hard<->soft skew blend, uniform and paintable per-region.

Cage push uses soft (welded) normals so it stays watertight over a hard-edged low
poly (fuse -> recompute -> peak), while the low poly keeps its hard normals for the
bake. Then **skew**: a per-region hard<->soft blend of the ray firing direction
(the Copernicus / Labs Maps Baker behaviour). Foundational for correct cages on
hard-surface assets; can be scheduled before Milestone 7.

## Dependencies

`pyvista`, `numpy`, `trimesh` (+ assimp and embree backends), `imageio`. Pure
`Plotter` for the MVP; `pyvistaqt` + `PySide6` is the deferred polished-UI path.

## Cross-cutting stretch goals

**All landed** - tracked with tests in [stretch-goals.md](stretch-goals.md), and the
larger gap analysis (persistence, brushes, exploded bake, etc.) in
[feature-gaps.md](feature-gaps.md):

- [x] Arbitrary (non-topology-matched) cages via nearest-point + normal interpolation.
- [x] Free 3-axis gizmo movement as a selectable default.
- [x] Additional bake maps (AO, curvature), supersampling, UV-island padding.
- [x] Cancellable bake with progress reporting.
- [x] Qt front end with file menu and docked panels.

## Beyond the milestones

Shipped since the original milestone plan, on top of the stretch list:

- **Project persistence** - save/load the edited cage (USD) and a full `.cbcproj`
  session (cage edits, skew map, bake settings, recipe, theme), recent files,
  drag-and-drop, unsaved-quit guard. See [feature-gaps.md](feature-gaps.md) section A.
- **Cage editing power** - push/inflate, smooth/relax brushes and X/Y/Z symmetry.
- **Ray-miss / projection feedback** - green/orange/red miss map plus a 3D overlay.
- **Headless CLI / batch bake** - `--bake` and `--bake-project` run window-less for CI.
- **Windows binary** - PyInstaller build published to GitHub Releases (`v*` tags).

**Experimental (in the codebase, not production-ready - not advertised):**

- **Auto-solve cage** (`autocage.py`) - a per-vertex offset field that probes,
  smooths upward, then verify-bakes and grows poke-through faces, optionally bending
  the firing direction into overhangs. Headless-tested and wired to an "Auto-solve
  cage" button, but the results are not yet reliable enough to lean on; treat it as a
  rough starting point an artist then refines by hand, not a finished feature.

## Verification

Headless `pytest` over `cage.py`, `meshio.py`, `bake.py`:

- `displace` pushes points exactly `normal * value` from the base.
- `validate_correspondence` passes on a duplicate, fails on mismatched count.
- `project_onto_normal` clamps an off-axis point back onto the normal line.
- `load_mesh` round-trips a tiny OBJ (and FBX where assimp is available) to the same
  vertex count/order; the count check fires on a split mesh.
- `bake` on a known pair yields flat regions near `(128,128,255)` with bumps
  deviating as expected; errors when the low poly has no UVs.

Manual interaction test:

```
python -m cagebakecake low.usdc --high high.usdc --cage cage.usdc --hdr env.hdr
```

Confirm by eye: cage transparent over high poly; high poly PBR-shaded and HDR-lit;
shift-drag rotates the lighting; displacement slider inflates/deflates the cage;
transparency slider works; picking a cage vertex shows the oriented gizmo and drag
moves only that vertex along its normal; the Bake button writes a normal-map PNG and
previews it on the low poly.
