# Phase 1.1 - Vertex picking

## Goal

Select the nearest cage vertex from a click and capture its index in editor state.

## Tasks

- [ ] Enable picking on the cage actor via `Plotter.enable_point_picking` (try
      `enable_surface_point_picking` as the alternative).
- [ ] Resolve the picked location to the nearest cage **vertex index** (VTK point id
      or a NumPy/KDTree nearest lookup against `cage.points`).
- [ ] Store the selected index on the editor (`self.selected_vertex`), `None` when
      nothing is selected.
- [ ] Give visual feedback for the selection (highlight the picked vertex, for
      example a small sphere glyph at `cage.points[index]`).
- [ ] Support deselect (click empty space or press Escape) and clear feedback.

## Notes

- Picking must target the cage, not the high poly or low poly; constrain the
  pickable actors so overlapping geometry does not steal the pick.
- Keep the index, not the position - downstream phases write back into
  `cage.points[index]`.
