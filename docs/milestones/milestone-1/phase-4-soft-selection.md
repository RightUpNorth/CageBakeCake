# Phase 1.4 - Soft selection (proportional editing)

## Goal

When a cage vertex is moved, move nearby vertices too with a smooth falloff, like
Maya soft-select / Blender proportional editing. Added as a new requirement after
the spike (not in the original Milestone 1 scope).

## Tasks

- [ ] Add a soft-selection radius control (and an on/off toggle).
- [ ] On selection, precompute the affected vertices within the radius and a falloff
      weight per vertex (e.g. smooth/smoothstep falloff, weight 1 at the center to 0
      at the radius).
- [ ] On drag, apply the gizmo delta scaled by each vertex's weight:
      `manual_delta[j] += delta * weight[j]`, then recompose and update the cage.
- [ ] Show the falloff region (e.g. color the affected points by weight) so the user
      sees the influence.

## Status

Implemented (`cage.soft_weights` + the editor wiring). Keys: `[o]` toggles soft
selection, `[` / `]` shrink/grow the radius. The drag applies the handle's world
move scaled by each neighbour's smoothstep weight (`manual_delta[j] = md0[j] +
move * w[j]`), and the affected region is shown as points coloured by weight
(plasma). Verified headless: weights fall off smoothly, only verts within the radius
move, the centre moves fully; verified visually as a smooth bump on MatBall.

## Notes

- Works through the same `manual_delta` + `cage.compose` path as single-vertex edits.
- MVP uses a **euclidean** radius for neighbor finding. Caveat: euclidean distance
  bleeds across disconnected-but-nearby surfaces (e.g. the gap between the ball and
  its base on MatBall). Geodesic/topological falloff is the correct fix and is a
  later refinement.
- Depends on the gizmo delta from Phase 1.2, so build after single-vertex gizmo
  motion is confirmed.
