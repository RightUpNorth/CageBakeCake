# Phase 3.1 - Slider widget

## Goal

Add the displacement slider and wire its callback.

## Tasks

- [ ] Add a `Plotter.add_slider_widget` for the global cage push with a sensible
      range and starting value.
- [ ] Implement `cage.displace(lowpoly_points, normals, value)` returning the pushed
      points (headless, testable).
- [ ] Connect the slider callback to recompute and update the cage `PolyData` points.
- [ ] Label the slider clearly in the viewport.

## Notes

- Keep `displace` pure (no plotting) so it can be unit-tested: pushing by `value`
  must move each point exactly `normal * value` from the base.
