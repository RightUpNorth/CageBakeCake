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
- **[med] Recent files**, drag-and-drop to open, and remembered window/dock layout.
- **[low] Persist undo history** (or at least warn on unsaved-edits quit).

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
- **[med] Smooth / relax brush** for the cage, to remove the lumps local edits create.
- **[low] Numeric entry** for a selected vertex's offset (precise nudge).

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
- **[high] Ray-miss / projection feedback. (PARTLY DONE)** The normal bake now also
  produces a "Ray miss" map (`bake.bake(..., return_miss=True)` -> `_miss_map`): green
  where a ray hit the high poly, red where it missed (the cage failed to reach a
  surface), shown in the bitmap viewer's Map dropdown. Still open: distinguishing
  too-tight (poke-through) from too-loose (wrong surface) misses, and a 3D in-viewport
  overlay of the missed regions on the low poly.
- **[high] Additive / incremental re-bake (explicitly requested).** When a cage edit
  only touches a small region, re-bake just the affected texels instead of the whole
  map. The re-bake step is the hot part of the core loop, and a full bake to re-do one
  corner is the main thing that makes iteration slow. Needs: track the dirty cage
  region (the set of vertices whose `manual_delta` / skew changed since the last bake),
  map it to the affected UV faces -> texel rectangle(s), re-cast only those texels, and
  composite the result over the previous bake buffer (`_baked_image`). Falls back to a
  full bake when no prior bake exists or the whole cage moved (e.g. the global offset
  slider). Pairs naturally with the bitmap viewer (show which region was refreshed) and
  with ray-miss feedback.
- **[med] More maps:** object/world-space normal, height/displacement, thickness, bent
  normal, position, material/color ID. Several reuse the existing ray cast.
- **[med] Output options:** 16-bit / EXR, flip-green (DirectX vs OpenGL), channel
  packing, sRGB vs linear control.
- **[med] UDIM / multi-tile UV** support for assets that span more than one 0-1 tile.
- **[low] Tangent-basis choice** (e.g. MikkTSpace) to match a target engine exactly.
- **[low] Bake presets** (save a named bake configuration).

## D. Inspection and feedback (the 2D side)

The app is almost entirely a 3D viewport; there is little 2D feedback.

- **[core] Bitmap viewer. (DONE)** A "Bake preview" dock (`imageview.ImageView`) shows
  the last baked map with a Normal / AO / Curvature dropdown and wheel-zoom / drag-pan;
  `CageEditor.baked_maps()` keeps all three in memory and the dock refreshes after each
  bake. Channel isolation is not yet implemented (possible follow-up).
- **[high] UV layout view.** Show the low poly's UV islands (and overlay the bake / ray
  coverage), so the artist can see seams, wasted space, and uncovered islands.
- **[med] Before/after split or difference view** for comparing a bake to the high poly.

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

- **[med] Threaded bake.** The bake runs on the UI thread (kept responsive by pumping
  events); a worker thread would keep the UI fully live and allow baking while editing.
- **[low] Large-mesh viewport handling** (LOD / decimated display for very dense high
  polys) - the high poly is ~12 GB resident at 6.5M points, so very dense assets will
  still pressure memory and render cost.

## G. Workflow / automation

- **[med] Batch / CLI bake** of many asset pairs without the GUI (the headless core
  already supports it; needs a CLI surface beyond `--screenshot`).
- **[low] Camera bookmarks / standard orthographic views**, isolation mode,
  backface-culling toggle.

## Summary - the short list

If the goal is "a credible cage *authoring* + baking tool," the load-bearing gaps are:

1. **Cage save/load** (A) - without it the tool cannot do its titular job end to end.
2. **Bitmap viewer** (D) - see what you baked.
3. **Ray-miss / projection feedback** (C) - know whether the cage is doing its job.
   (Core "Ray miss" map done; tight-vs-loose split and 3D overlay still open.)
4. **Push/inflate brush + symmetry** (B) - make cage editing fast, not vertex-by-vertex.
5. **Exploded / per-part bake** (C) - correct multi-part bakes.

Everything else is valuable but sits behind these five - with one explicitly-requested
addition that rides alongside them:

6. **Additive / incremental re-bake** (C) - re-bake only the region a cage edit
   changed, so iterating on a cage does not pay for a full bake each pass. This is the
   iteration-speed half of the loop and a priority feature, not a someday item.
