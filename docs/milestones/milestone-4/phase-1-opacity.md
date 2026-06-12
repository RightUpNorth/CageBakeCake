# Phase 4.1 - Opacity slider

## Goal

Add the cage transparency control.

## Tasks

- [ ] Add a second `Plotter.add_slider_widget` ranged 0..1 for cage opacity.
- [ ] In the callback, set the cage actor's opacity (`actor.prop.opacity`).
- [ ] Ensure it only affects the cage actor, not the low/high poly.
- [ ] Choose a sensible default (cage clearly visible but see-through).
- [ ] Position/label the slider so it does not overlap the displacement slider.

## Notes

- Trivial milestone; mostly UI placement. Reference: `docs/interaction.md`.
