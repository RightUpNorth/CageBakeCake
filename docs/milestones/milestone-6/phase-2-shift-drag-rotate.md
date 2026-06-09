# Phase 6.2 - Shift-drag rotate

## Goal

Rotate the HDR environment by holding shift and dragging, so lighting direction is
art-directable without placing lights.

## Tasks

- [ ] Add a VTK mouse-move observer that checks the shift modifier state.
- [ ] While shift is held during a left-drag, accumulate a yaw angle from the
      horizontal mouse delta.
- [ ] Apply the yaw to re-orient the environment texture and re-render.
- [ ] Ensure normal (no-shift) drag still orbits the camera as usual - do not consume
      the event when shift is not held.
- [ ] Pick a comfortable drag-to-rotation sensitivity.

## Notes

- Only yaw is required for the MVP; pitch is an optional extra.
- Reference: `docs/interaction.md` (HDR shift-drag).
