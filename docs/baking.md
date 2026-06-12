# Baking

The Bake button produces a **tangent-space normal map** that transfers high-poly
surface detail onto the low poly, using the cage to bound the projection. This is
the cage's entire reason for existing: it gives the outer limit of each ray so the
baker captures the intended high-poly surface and not something behind it.

This is the heaviest milestone. It is implemented in `bake.py` as pure, headless
NumPy + trimesh, so it can be tested without a window.

## Inputs

- Low poly with **UVs** (required - the bake fails clearly if the low poly has no UV
  coordinates).
- The current cage offset (per-vertex outer ray limit).
- High poly (the detail source).
- Output resolution `N` (the map is `N x N`).

## Algorithm

1. **Build an acceleration structure** - a `trimesh` BVH over the high poly for fast
   ray intersection. Use the embree backend when available; the pure-Python caster
   works but is slow on dense meshes.
2. **Rasterize the low-poly UV layout** into the `N x N` buffer. For each texel
   covered by a low-poly triangle, compute its barycentric coordinates.
3. **Per covered texel**, interpolate from the triangle's vertices:
   - the 3D surface position (the ray start),
   - the vertex normal (the ray direction),
   - the tangent basis (tangent, bitangent, normal) for that texel.
4. **Cast a ray** from the surface position along the normal, bounded by the cage
   offset at that point, and find the nearest high-poly hit.
5. **Read the high-poly normal** at the hit (barycentric-interpolated across the hit
   triangle), in world space.
6. **Transform** the world-space hit normal into the texel's tangent space, encode
   it to RGB (`x,y,z` in `[-1,1]` mapped to `[0,255]`), and store it.
7. **Write** the buffer to a PNG via `imageio`, and preview it on the low poly as a
   texture.

A flat surface bakes to roughly `(128, 128, 255)` - the convention for "normal
points straight out of the surface" - which is the easy thing to assert in tests.

## Tangent space

The encoded normal is relative to each texel's tangent frame, so the map is
reusable as the low poly deforms or is instanced. The tangent and bitangent are
derived from the UV gradients across each triangle; the third axis is the
interpolated vertex normal. (Matching a specific engine's exact tangent convention -
for example MikkTSpace - is a refinement, not an MVP requirement.)

## MVP scope and stretch goals

**MVP:** a single tangent-space normal map at a chosen resolution, one ray per
texel.

**Stretch goals (explicitly out of MVP):**
- Ambient occlusion, curvature, position, and other map types.
- Anti-aliased supersampling (multiple rays per texel).
- Edge padding / dilation of the UV islands.
- A cancellable bake with a progress log (important without embree, where dense
  meshes are slow).
