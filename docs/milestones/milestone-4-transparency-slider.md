# Milestone 4 - Transparency slider

## Goal

A slider that sets the cage's opacity so the artist can see the high poly through it.

## Phases

1. [Phase 4.1 - Opacity slider](milestone-4/phase-1-opacity.md)

## Status

Implemented alongside Milestone 3: a bottom-right `add_slider_widget` (0..1) drives
`cage_actor.prop.opacity`, affecting only the cage. See
[milestone-3-displacement-slider.md](milestone-3-displacement-slider.md).

## Exit criteria

- The slider drives the cage actor's opacity from solid to nearly invisible without
  affecting the other meshes.

## References

- `docs/interaction.md` - transparency slider.
