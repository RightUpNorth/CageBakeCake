# Feature-gap investigation

An investigation into what a bake-cage authoring tool plausibly needs that
CageBakeCake does not yet have, measured against how artists actually use cage +
baking tools (Marmoset Toolbag, Substance 3D Painter/Designer bakers, xNormal,
Handplane, Houdini/Dynamite). It is a survey, not a commitment - the roadmap decides
what is in scope. Each item carries a rationale and a rough priority.

Priority legend: **[core]** part of the central loop and arguably already expected;
**[high]** strong value, common in peer tools; **[med]** useful, situational;
**[low]** nice-to-have / polish.

## A. Persistence and project state - the biggest structural gap

Today **nothing survives closing the window**: cage edits, the skew map, slider
values, undo history, and loaded paths are all in-memory only. The only thing written
to disk is a baked PNG (and `[c]` create-cage, which copies the *source* low poly, not
the edited cage).

- **[core] Save / load the edited cage. (DONE)** `meshio.save_mesh` writes the authored
  cage to USD in the canonical frame and `CageEditor.save_cage` / File > Save Cage As...
  expose it; loading a cage already existed (`--cage` / resample). The app is now a cage
  *authoring* tool end to end, not just a baker.
- **[high] Save / load a project / session. (DONE)** `project.py` writes a `.cbcproj`
  (JSON) holding the mesh paths, the cage edits (global push + a sparse per-vertex manual
  delta), the skew map, the bake settings, the recipe and the theme; File > Save Project
  As... / Open Project... expose it. `CageEditor.authoring_state` / `apply_authoring_state`
  carry the editor half, mesh paths are stored relative to the project file for
  portability, and a changed source mesh (vertex-count mismatch) skips just the per-vertex
  arrays and keeps the rest. So a cage edit now survives a restart and is resumable.
- **[med] Recent files + drag-and-drop. (DONE)** A QSettings-backed File > Open Recent
  submenu (`project.mru_add` is the pure MRU helper - front-move, path-normalized dedup,
  capped), updated on every mesh / project open; and the window accepts drag-and-drop of
  `.usd*` / `.cbcproj` files to open them. Still open: remembered window/dock layout.
- **[low] Warn on unsaved-edits quit. (DONE)** Closing with cage edits that differ from the
  last saved/opened baseline (push + manual delta + skew; bake settings excluded so they
  don't nag) prompts Save / Discard / Cancel. Persisting the full undo history is still
  open.

## B. Cage editing power

Current editing is: one global push slider, per-vertex gizmo (normal / tangent / free),
soft-select falloff, and paintable skew. Strong start; the gaps are the high-leverage
brushes and selection tools artists expect.

- **[high] Push / inflate brush. (DONE)** `CageEditor.push_brush_at` + the "Push brush"
  dock toggle/strength slider paint the cage offset directly: left-drag pushes the
  soft-radius region under the cursor out (or in, with a negative strength) along the
  normals, accumulated into `manual_delta` so it composes with the global offset and is a
  single undo step. Backed by the existing soft-weight infrastructure; mutually exclusive
  with skew paint.
- **[high] Symmetry / mirror editing (X/Y/Z). (DONE)** `set_symmetry` + the "Symmetry"
  segmented control mirror an edit to the opposite side: `cage.mirror_index` pairs each
  cage vertex with its counterpart across the bbox midplane (O(V) quantized lookup), and
  every gizmo drag / brush stroke reflects the touched side's `manual_delta` onto its
  mirror (`cage.reflect_axis`). Asymmetric vertices with no partner are left untouched.
- **[med] Multi-vertex selection** (box / lasso / paint-select) so a region can be
  pushed together without soft-select falloff.
- **[med] Smooth / relax brush. (DONE)** `CageEditor.smooth_brush_at` + the "Smooth brush"
  dock toggle/strength relax the cage: left-drag pulls each affected vertex toward the
  average of its triangulation neighbours (Laplacian, adjacency built once) by
  strength*weight into manual_delta, so it composes, undoes as one stroke and mirrors with
  symmetry. The third mutually-exclusive left-drag brush (push / skew / smooth).
- **[low] Numeric entry. (DONE)** A "Selected offset" dock spin box shows and sets the
  picked vertex's manual normal-offset (`CageEditor.selected_offset` /
  `set_selected_offset`, preserving any tangential edit); an editor on-select callback
  keeps it following viewport picks.

## C. Baking - more map types and correctness feedback

Current bakes: tangent-space normal, AO, curvature. Supersampling, edge padding, and a
cancellable run already exist. Peer bakers ship a wider map set and, importantly, tell
you when the bake went wrong.

- **[high] Exploded bake / per-object cage offset. (DONE)** An "Explode bake" dock slider
  drives `CageEditor._exploded_geometry`: before baking, each part is pushed radially out
  from the scene centre by factor*(part centroid - centre) via `bake.explode_translation`
  (low, cage and high together; the cage shares the low's indexing). A matched low/high
  pair shares a centroid and moves as one, while distinct parts diverge, so neighbours
  stop cross-projecting. The BVH is rebuilt over the moved high poly (the in-place cache
  is bypassed); the encode is translation-invariant, so the map is unchanged but for the
  removed cross-hits. Applies to the normal and AO bakes and saves with the project.
- **[high] Ray-miss / projection feedback. (DONE)** The normal bake produces a "Ray miss"
  map (`bake.bake(..., return_miss=True)`) shown in the bitmap viewer's Map dropdown, now
  three-way: green where a ray hit the high poly, **orange where the high poly pokes out
  beyond the cage (too tight)** and **red where nothing was found nearby (too loose)**.
  The poke-through split comes from a second, outward cast on just the missed texels. With
  `return_face_miss=True` the bake also returns a per-low-face class, which drives a **3D
  in-viewport overlay** (`CageEditor.set_miss_overlay`, View menu / `[m]` / dock toggle)
  painting the missed low-poly faces orange/red over the surface.
- **[high] Additive / incremental re-bake (explicitly requested). (DONE)**
  `CageEditor.rebake` (Bake > Re-bake changed region / dock "Re-bake region") diffs the
  current cage against the snapshot the last full bake stored (`_baked_cage_points`),
  finds the moved vertices, maps them to the dirty low-poly faces, and re-casts only those
  via `bake.rebake_faces` - which rasterizes just that face subset (the rasterizer takes a
  `faces=` arg now) and composites over the previous `_baked_image` (covered texels that
  newly miss reset to flat). It falls back to a full bake when there is no prior bake, the
  bake size / explode factor changed, supersampling is on, or most of the cage moved (then
  a full bake is cleaner). So iterating on one corner of a cage no longer pays for a whole
  map. Still open: refreshing the ray-miss map incrementally too.
- **[med] More maps. (PARTLY DONE)** Object/world-space normal (`bake.bake(..., space=
  "object")`), height/displacement (`bake.bake_height` - signed low-surface-to-hit distance
  along the normal) and world position (`bake.bake_position` - hit position over the high
  bbox) all bake now, reusing the cage-bounded cast (height/position via a shared
  per-texel-geometry helper + a location cast). All three feed the recipe (BAKEABLE_KINDS),
  the batch/CLI baker, the Bake menu and the bitmap viewer. Thickness too
  (`bake.bake_thickness` - inward distance to the far wall, for translucency masks). Still
  open: bent normal, material/color ID.
- **[med] Output options. (PARTLY DONE)** Flip-green (`bake.flip_green`, dock "Flip green
  (DirectX)") inverts the normal map's G channel for the DirectX/OpenGL convention,
  applied to the normal bake / re-bake and saved with the project; channel packing already
  exists (the recipe). Still open: 16-bit / EXR output, sRGB-vs-linear control.
- **[med] UDIM / multi-tile UV** support for assets that span more than one 0-1 tile.
- **[low] Tangent-basis choice** (e.g. MikkTSpace) to match a target engine exactly.
- **[low] Bake presets** (save a named bake configuration).

## D. Inspection and feedback (the 2D side)

The app is almost entirely a 3D viewport; there is little 2D feedback.

- **[core] Bitmap viewer. (DONE)** A "Bake preview" dock (`imageview.ImageView`) shows
  the last baked map with a Normal / AO / Curvature dropdown and wheel-zoom / drag-pan;
  `CageEditor.baked_maps()` keeps all three in memory and the dock refreshes after each
  bake. Channel isolation is not yet implemented (possible follow-up).
- **[high] UV layout view. (DONE)** The 2D pane now draws the low poly's UV island layout
  via `uvlayout.layout_image` (vectorized edge rasterization over the per-corner UVs): the
  island wireframe / seams over a checkerboard when nothing is baked, or over the selected
  baked map when one exists (the bake is already in UV space, so this is a UV-space texture
  view with seams). Islands vs the checker show wasted UV space; the baked map under the
  wireframe shows coverage. Replaces the placeholder stand-in that mirrored the tray map.
- **[med] Before/after difference view. (DONE)** The bitmap viewer gains "Pin ref" (snapshot
  the current map as the 'before') and a "Diff" toggle that shows `bake.diff_map` - a
  grayscale heatmap of the per-pixel difference (black where identical, brighter where they
  diverge) - so two bakes can be compared. Same-size maps only (it warns otherwise).

## E. Import / format reach

Runtime is USD-only; FBX/OBJ are converted offline via Blender.

- **[med] Convert-on-load** for FBX/OBJ (shell out to the existing Blender converter
  automatically) so artists are not blocked on a manual preprocess.
- **[low] glTF/PLY/STL direct read** (VTK can read several of these already).

## F. Performance and scale

A profiling pass (cProfile + scalene + py-spy, on the 6.5M-point bin high poly) found
two hotspots, both now addressed:

- **Bake BVH rebuild (DONE).** ~40% of each bake was rebuilding the embree BVH over the
  unchanged high poly. `bake.make_ray_mesh` builds it once and `CageEditor` reuses it
  across bakes (`ray_mesh=`), cutting repeat bakes ~23s -> ~8s. This is also the
  foundation for additive re-bake (item C).
- **Per-mouse-move render/pick (DONE).** Hover cell-picked the whole scene and
  re-rendered on every move. Hover now uses a cage-only picker and skips the render when
  the hovered vertex is unchanged.

Still open:

- **[med] Threaded bake. (DONE)** The normal and AO bakes now run their ray cast on a
  worker thread (`window._BakeWorker` on a `QThread`), so the viewport stays fully live -
  no more `processEvents` pumping. `CageEditor.bake_inputs` / `ao_inputs` snapshot the pure
  arguments on the main thread (copying the cage / firing normals so a concurrent edit
  can't corrupt a running bake; the immutable high poly + BVH pass by reference);
  `bake.bake` / `bake_ao` run on the thread; `apply_bake_result` / `apply_ao_result` do the
  VTK/actor updates back on the main thread. Bakes don't overlap (a busy guard), and a
  close mid-bake cancels and joins the worker. The recipe pack and Export stay synchronous
  (a deliberate one-shot), and the standalone Plotter path keeps the original `_bake`.
- **[low] Large-mesh viewport handling** (LOD / decimated display for very dense high
  polys) - the high poly is ~12 GB resident at 6.5M points, so very dense assets will
  still pressure memory and render cost.

## G. Workflow / automation

- **[med] Batch / CLI bake. (DONE)** `cagebakecake/batch.py` bakes straight from
  meshio + cage + bake with no window and no GL: `bake_pair` bakes a low/high (+ optional
  cage) pair to per-type PNGs (`--bake --maps normal,objnormal,ao,curv --size --ss
  --padding --flip-green --out`), and `bake_project` re-bakes a saved `.cbcproj`'s recipe
  with its cage edits and bake settings (`--bake-project shot.cbcproj`). Both exit without
  opening the GUI, so they run in a pipeline / CI. Headless-tested + a CLI smoke.
- **[low] Camera bookmarks / standard orthographic views**, isolation mode,
  backface-culling toggle.

## Summary - the short list

If the goal is "a credible cage *authoring* + baking tool," the load-bearing gaps are:

1. **Cage save/load** (A) - without it the tool cannot do its titular job end to end.
2. **Bitmap viewer** (D) - see what you baked.
3. **Ray-miss / projection feedback** (C) - know whether the cage is doing its job.
   (Done: green/orange/red miss map with poke-through vs too-loose, plus a 3D overlay.)
4. **Push/inflate brush + symmetry** (B) - make cage editing fast, not vertex-by-vertex.
5. **Exploded / per-part bake** (C) - correct multi-part bakes.

Everything else is valuable but sits behind these five - with one explicitly-requested
addition that rides alongside them:

6. **Additive / incremental re-bake** (C) - re-bake only the region a cage edit
   changed, so iterating on a cage does not pay for a full bake each pass. This is the
   iteration-speed half of the loop and a priority feature, not a someday item.
