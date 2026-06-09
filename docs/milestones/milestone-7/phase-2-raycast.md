# Phase 7.2 - Cage-bounded ray casting

## Goal

For each sampled texel, cast a ray into the high poly bounded by the cage and capture
the high-poly normal at the hit.

## Tasks

- [ ] Build a `trimesh` BVH over the high poly (use the embree backend when
      available).
- [ ] For each texel, cast a ray from the surface point along the normal, bounded by
      the cage offset at that point (the cage is the outer limit).
- [ ] Find the nearest high-poly hit; record misses for later handling.
- [ ] Read the high-poly normal at the hit, barycentric-interpolated across the hit
      triangle, in world space.

## Notes

- The cage bound is what prevents capturing surface behind the intended one.
- Ray *direction* should come from the soft (welded) cage normals, optionally skewed
  per region between hard and soft - see
  [Milestone 8](../milestone-8-normals-skew.md). The cage decides the outer bound;
  skew decides the direction.
- Without embree this is slow on dense meshes - keep the loop vectorized where
  possible and plan for the progress/cancel stretch goal.
- Reference: `docs/baking.md` (algorithm steps 1, 4-5).
