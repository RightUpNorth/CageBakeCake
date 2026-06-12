# Phase 2.3 - Register the actors

## Goal

Show the three meshes in the viewport, styled so they stay readable when overlapping.

## Tasks

- [ ] Add the high poly as an opaque, shaded surface (PBR comes in Milestone 5; a
      plain lit surface is fine here).
- [ ] Add the low poly as a wireframe.
- [ ] Add the cage as a semi-transparent surface drawn over the high poly.
- [ ] Keep a handle to each actor on the editor for later updates (opacity, points,
      shading).
- [ ] Frame the camera to fit all three on load.

## Notes

- Only the cage actor should be pickable in Milestone 1's interaction; set
  pickability accordingly here.
- Reference: `docs/interaction.md` (three actors).
