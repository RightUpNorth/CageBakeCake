# Milestone 6 - HDR environment + shift-drag rotate

## Goal

Light the scene with an HDR environment map and let the artist "move the light" by
shift-dragging to rotate the HDR, instead of placing point lights.

## Phases

1. [Phase 6.1 - HDR environment](milestone-6/phase-1-hdr-environment.md)
2. [Phase 6.2 - Shift-drag rotate](milestone-6/phase-2-shift-drag-rotate.md)

## Status

Implemented, with one deviation. `set_environment_texture` gives the PBR high poly
ambient image-based lighting + reflections, from an `--hdr` equirectangular image or
a built-in procedural sky (no external asset needed; falls back to procedural if the
HDR fails to load).

Deviation from the original plan ("rotate the HDR" on shift-drag): in this VTK build
the IBL is baked once and does not re-orient live from `SetEnvironmentUp/Right` or
the `rotation` arg (verified - the render is unchanged). So **shift-drag orbits a
directional key light** (azimuth about world-up Z) instead, which is live and clearly
visible, while the HDR provides static ambient + reflections. This achieves the goal
("move the lighting") even though it is a movable light layered on the HDR rather
than the HDR itself rotating.

## Exit criteria

- An `.hdr` lights the PBR high poly and provides reflections.
- Shift + left-drag rotates the environment lighting interactively.
- With no HDR supplied, a default 3-point light rig is used instead.

## References

- `docs/interaction.md` - HDR environment and shift-drag.
- `docs/architecture.md` - imageio for HDR read.
