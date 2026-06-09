# Interaction

The viewport is a single PyVista `Plotter` hosting three actors and a small set of
widgets. Everything below is a thin callback layer over the headless math in
`cage.py`.

## The three actors

| Mesh | Style | Purpose |
| --- | --- | --- |
| High poly | PBR-shaded, opaque | The detail source; what you bake from. |
| Low poly | Wireframe | The bake target; reference for cage shape. |
| Cage | Semi-transparent surface | The editable envelope, drawn over the high poly. |

Distinct styling keeps the three readable when overlapping.

## Displacement slider

`Plotter.add_slider_widget` drives the global cage push. Its callback recomputes the
cage points as `base + normal * value + manual_delta` (see `docs/cage-model.md`) and
writes them back into the cage `PolyData`, so the slider and per-vertex edits
coexist.

## Transparency slider

A second `add_slider_widget` sets the cage actor's opacity directly
(`actor.prop.opacity`), from solid down to nearly invisible, so the artist can see
where the cage sits relative to the high poly.

## Vertex picking and the normal-oriented gizmo

This is the only genuinely uncertain piece of the interaction, so it is built and
verified first.

1. **Pick** - `Plotter.enable_point_picking` (or `enable_surface_point_picking`)
   selects the nearest cage vertex and captures its index.
2. **Show the handle** - oriented to that vertex's low-poly normal. Candidate
   primitives, in order of preference (simplest first):
   1. `add_line_widget` placed along the normal - gives axis-constrained drag, which
      is exactly the classic cage push. Preferred if it works.
   2. `add_sphere_widget` for free drag, then `project_onto_normal` to clamp the
      returned position back onto the normal line.
   3. Raw VTK `vtkAxesTransformWidget`, only if neither of the above suffices.
3. **Apply** - on drag, update `manual_delta[index]` and write the new position into
   the cage `PolyData` at that index, then re-render.

**Default motion is normal-constrained push** (1 axis along the low-poly normal).
Free 3-axis movement (gizmo oriented to the normal but unclamped) is a stretch goal
behind a toggle or modifier; the `cage.py` math already supports both, so switching
is a GUI-only change.

## Simple shader

The high poly is drawn with PyVista PBR:

```
plotter.add_mesh(high, pbr=True, metallic=..., roughness=..., smooth_shading=True)
```

so it reads as a lit surface rather than flat color. Metallic/roughness sliders are
an optional stretch.

## HDR environment and shift-drag to rotate

Lighting is image-based, not hand-placed:

- An `.hdr` equirectangular map is loaded with
  `Plotter.set_environment_texture(hdr, is_srgb=False)`. It both lights the PBR high
  poly and supplies reflections.
- **Shift + left-drag** rotates the environment. A VTK mouse-move observer checks the
  shift modifier and accumulates a yaw angle that re-orients the HDR, so the artist
  "moves the light" by spinning the environment.
- If no HDR is supplied, the app falls back to a default 3-point light rig.

## Bake button

A `Plotter.add_checkbox_button_widget` (or key bind) triggers the bake, writes a PNG,
and previews it on the low poly as a texture. The algorithm is described in
`docs/baking.md`.
