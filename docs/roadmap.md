# Roadmap

Milestones are ordered **riskiest first**. Milestone 1 is the only genuinely
uncertain piece; everything after it is standard PyVista wiring over the headless
math.

## Milestone 1 - Pick, gizmo, single-vertex update

Detail and phases: [milestone-1-pick-gizmo.md](milestones/milestone-1-pick-gizmo.md)

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

`meshio.load_mesh` for low/cage/high; validate cage-to-low correspondence and error
clearly on mismatch; register three distinctly styled actors.

## Milestone 3 - Displacement slider

Detail and phases: [milestone-3-displacement-slider.md](milestones/milestone-3-displacement-slider.md)

`add_slider_widget` -> recompute `base + normal * value + manual_delta` -> update
cage points. Layered so it does not wipe per-vertex edits.

## Milestone 4 - Transparency slider

Detail and phases: [milestone-4-transparency-slider.md](milestones/milestone-4-transparency-slider.md)

`add_slider_widget` -> set the cage actor's `opacity`.

## Milestone 5 - Simple shader

Detail and phases: [milestone-5-shader.md](milestones/milestone-5-shader.md)

PBR on the high poly (`pbr=True`, metallic/roughness, `smooth_shading=True`).
Metallic/roughness sliders optional.

## Milestone 6 - HDR environment + shift-drag rotate

Detail and phases: [milestone-6-hdr-lighting.md](milestones/milestone-6-hdr-lighting.md)

`set_environment_texture(hdr)` for lighting and reflections; shift-drag observer
accumulates a yaw angle to rotate the HDR; fall back to a 3-point rig with no HDR.

## Milestone 7 - Bake button (heaviest)

Detail and phases: [milestone-7-bake.md](milestones/milestone-7-bake.md)

`bake.py`: rasterize low-poly UVs, cast surface -> cage -> high rays via trimesh,
encode the high-poly normal into tangent space, write a PNG, preview on the low
poly. Requires UVs. MVP is a tangent-space normal map only.

## Milestone 8 - Hard/soft normals: watertight cage + skew

Detail and phases: [milestone-8-normals-skew.md](milestones/milestone-8-normals-skew.md)

Cage push uses soft (welded) normals so it stays watertight over a hard-edged low
poly (fuse -> recompute -> peak), while the low poly keeps its hard normals for the
bake. Then **skew**: a per-region hard<->soft blend of the ray firing direction
(the Copernicus / Labs Maps Baker behaviour). Foundational for correct cages on
hard-surface assets; can be scheduled before Milestone 7.

## Dependencies

`pyvista`, `numpy`, `trimesh` (+ assimp and embree backends), `imageio`. Pure
`Plotter` for the MVP; `pyvistaqt` + `PySide6` is the deferred polished-UI path.

## Cross-cutting stretch goals

- Arbitrary (non-topology-matched) cages via nearest-point + normal interpolation.
- Free 3-axis gizmo movement as a selectable default.
- Additional bake maps (AO, curvature), supersampling, UV-island padding.
- Cancellable bake with progress reporting.
- Qt front end with file menu and docked panels.

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
python -m cagebakecake low.obj cage.obj high.obj --hdr env.hdr
```

Confirm by eye: cage transparent over high poly; high poly PBR-shaded and HDR-lit;
shift-drag rotates the lighting; displacement slider inflates/deflates the cage;
transparency slider works; picking a cage vertex shows the oriented gizmo and drag
moves only that vertex along its normal; the Bake button writes a normal-map PNG and
previews it on the low poly.
