# Phase 7.4 - Bake button and preview

## Goal

Wire the headless bake to a viewport button and show the result on the low poly.

## Tasks

- [ ] Add a `Plotter.add_checkbox_button_widget` (or key bind) that triggers the bake
      with the current low poly, cage offset, and high poly.
- [ ] Choose the output resolution `N` and the PNG output path.
- [ ] Apply the returned normal map as a texture preview on the low poly.
- [ ] Surface bake errors (no UVs, unreadable mesh) clearly in the UI.
- [ ] Log progress during the bake (foundation for the cancellable-bake stretch
      goal).

## Notes

- The heavy lifting lives in `bake.py`; this phase is the thin GUI trigger and
  preview.
- Reference: `docs/interaction.md` (bake button), `docs/baking.md`.
