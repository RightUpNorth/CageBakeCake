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

- [x] **Arbitrary (non-topology-matched) cage** - `cage.resample_cage` casts each low
      vertex along its normal to the loaded cage (nearest cage vertex on a miss), turning
      a non-matching cage into an editable topology-matched base. The app uses it
      automatically when the cage vertex count differs from the low poly.
- [ ] **Paintable skew** - per-region skew weight map instead of a single value.
      `blend_normals` already takes a per-vertex skew; needs a paint UI (desktop check).
- [ ] **Free 3-axis gizmo** - move a vertex on all axes, not only along the normal.
      (desktop check)

## Bake UX

- [x] **Cancellable bake with progress** - `bake.bake` / `bake.bake_ao` take a
      `should_cancel` predicate and emit progress; they return None when cancelled. The
      dock shows live progress and a "Cancel bake" button (the bake runs on the UI thread
      and pumps events via the progress callback, so cancel and per-sample AO progress
      stay responsive). The AO bake is fully interruptible per sample; the normal bake's
      single ray cast is one embree call, so it can only be cancelled before the cast.

## Housekeeping

- [x] Replaced the stale README Status / "Design phase" / `--push 0.003` snippet with an
      accurate status and quickstart.
- [x] Marked the milestone-7 follow-ups (converter reconciliation, scale-relative push)
      resolved.
