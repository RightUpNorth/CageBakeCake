# Viewport / UI task list

Tracking the viewport and display-control work requested on top of the Qt front
end (PR #11). Grouped by area; check items off as they land. Each interactive item
needs a look on the desktop - the Qt + GL viewport cannot be verified headlessly.

## Done

- [x] **requirements.txt** - pin the tested dependency versions (merged, PR #12).
- [x] **Qt front end** - menu bar + docked controls around the viewport (PR #11).

## Display modes

- [x] **Low poly material switch** - toggle the low poly between wireframe and a lit
  shaded material. Wireframe is the default. (`[l]` / dock / View menu)
- [x] **Greyscale lit material** - a plain grey PBR material on the low poly so the
  HDR lighting (and shift-drag light rotation) visibly reacts to the surface.
- [x] **Normal-map toggle** - show the shaded low poly with / without the baked
  tangent-space normal map (`[n]`). VTK `SetNormalTexture` + `vtkPolyDataTangents`.
  *Needs a visual check on the desktop - orientation / channel handedness may want a
  tweak.*
- [x] **High poly material switch** - the same wireframe/shaded toggle for the high
  poly, independent of the low poly's setting (`[L]`).
- [x] **Cage stays visible while rendered** - the old full-screen bake preview is
  gone; baking now switches the low poly to shaded + normal map and the cage / points
  stay visible.
- [x] **Bake size** - independent width and height dropdowns, 256 ... 16384 (powers of
  two); a non-square map is allowed. `bake.bake` now takes `(width, height)`.
- [x] **High poly visibility toggle** - a dock checkbox / menu item to turn the high
  poly off (it is opaque and can occlude the cage).
- [x] **Low / high wireframe overlay** - a wireframe (edge) overlay toggle on the
  shaded low and high poly, independent of the material switch.
- [x] **Cage points not visible** - the cage-point actor now uses the same
  coincident-topology polygon offset as the gizmo handles, so the points draw in front
  of the translucent cage surface instead of losing the depth fight. *Confirm on the
  desktop; if still hidden it is the opaque high poly - turn it off.*

## Cage visibility

- [x] **Cage points toggle** - show / hide the orange cage points (`[k]`); point size
  bumped so they read.
- [x] **Cage wireframe toggle** - show / hide a cage wireframe overlay (`[j]`).

## Inspection

- [x] **View low-poly normals** - toggle normal glyphs on the low poly (`[v]`).

## Selection

- [x] **Click-empty-to-deselect** - a left click on empty viewport space (not a drag,
  not on a handle or the mesh) clears the selection and removes the gizmo (also `[d]`).
  Active style is `InteractorStyleTrackballCamera`; the priority-10 release observer
  fires on a click, so press + move-threshold + release works. *Needs a desktop check
  that release fires for a plain click.*

## Per-mesh visibility (needs a decision)

- [ ] **Per-mesh checklist** - a checklist of the meshes in each file; toggling an
  entry shows / hides that mesh.
- [ ] **Name-match toggle** - match low and high sub-meshes by name.

  Findings from the current assets:
  - Most files hold a single mesh. `bin_lp` holds two (`uv_fix` 3049 pts +
    `uv_fix_001` 237 pts); the app currently loads only the largest prim, silently
    dropping `uv_fix_001`. A real per-mesh checklist means loading *all* prims as
    separate, individually-toggleable actors (a `meshio` + `app` change).
  - Low and high prim names do not match (`uv_fix` vs `trash_can` / `mesh`), so
    name-matching between low and high is not meaningful for these assets.
  - Open question: load all sub-meshes now and add the per-file checklist, or defer
    until an asset actually needs it?

## Notes

- Independent low/high material state is required - do not unify the two switches.
- Toggles are exposed both as Qt dock controls / menu actions and as viewport
  keyboard shortcuts where the key does not collide with a VTK built-in
  (`w`/`s`/`r`/`p`/`e`/`q`/`f`).
