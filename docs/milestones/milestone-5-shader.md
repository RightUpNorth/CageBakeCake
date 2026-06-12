# Milestone 5 - Simple shader

## Goal

Render the high poly with a simple PBR material so it reads as a lit surface rather
than flat color.

## Phases

1. [Phase 5.1 - PBR material](milestone-5/phase-1-pbr-material.md)
2. [Phase 5.2 - Material sliders (stretch)](milestone-5/phase-2-material-sliders.md)

## Status

Implemented. The high poly renders with `pbr=True, metallic=0.15, roughness=0.5,
smooth_shading=True`, lit by the HDR/procedural environment (Milestone 6). Low poly
stays wireframe, cage stays semi-transparent. Metallic/roughness sliders remain a
stretch.

## Exit criteria

- The high poly shows PBR shading with sensible default metallic/roughness.
- Low poly stays wireframe and cage stays semi-transparent.

## References

- `docs/interaction.md` - simple shader.
