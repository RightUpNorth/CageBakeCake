# Stretch goals

The roadmap milestones (M1-M8) are complete; these are the cross-cutting stretch
items. Headless-verifiable ones are done with tests; GUI-heavy ones note a desktop
caveat. Check off as they land.

## Bake quality (headless)

- [x] **Supersampling** - `bake.bake(supersample=N)` bakes at NxN and box-averages the
      tangent-space normals (renormalized) down. Dock "Supersample" dropdown (1x/2x/4x).
- [x] **UV-island padding / dilation** - `bake.bake(padding=px)` bleeds island colours
      `px` texels into the background (nearest filled texel). Dock "Edge padding" dropdown.

## Extra maps (headless)

- [x] **Ambient occlusion** - `bake.bake_ao`: cosine-weighted hemisphere rays per texel,
      fraction blocked by the high poly within `max_dist`. Dock "Bake AO" + "AO samples".
- [x] **Curvature** - `bake.curvature_from_normal_map`: divergence of the tangent
      normal's xy (convex bright, concave dark, flat neutral). Dock "Bake Curvature"
      (uses the last normal-map bake).

## Cage / interaction

- [ ] **Arbitrary (non-topology-matched) cage** - nearest-point + normal interpolation
      so a cage that is not a vertex-for-vertex duplicate still works. (headless)
- [ ] **Paintable skew** - per-region skew weight map instead of a single value.
      `blend_normals` already takes a per-vertex skew; needs a paint UI (desktop check).
- [ ] **Free 3-axis gizmo** - move a vertex on all axes, not only along the normal.
      (desktop check)

## Bake UX

- [ ] **Cancellable bake with progress** - core cancellation hook is headless; the
      threaded Qt progress/cancel UI needs a desktop check.

## Housekeeping

- [ ] Remove the stale `--push 0.003` test snippet from the README.
- [ ] Mark the milestone-7 follow-ups (converter reconciliation, scale-relative push)
      resolved instead of open.
