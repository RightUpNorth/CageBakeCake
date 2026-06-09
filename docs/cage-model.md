# Cage Model

## The topology-matched cage assumption

A bake cage is a **vertex-for-vertex duplicate of the low poly**: the same vertex
count, in the same order, just pushed outward. This is exactly what production
bakers (Substance, Marmoset, xNormal) require, and the whole design leans on it.

Concretely, for every cage vertex index `i`:

- It corresponds to low-poly vertex `i`.
- Its outward push direction is the low-poly vertex normal `i`.

This single assumption makes every feature trivial arithmetic instead of a search
problem.

### Why we do not support arbitrary cages in the MVP

If the cage were an independent mesh with its own topology, every operation would
need a nearest-point lookup and normal interpolation from the low poly, the
correspondence would be approximate, and the gizmo orientation would be ambiguous.
That balloons the design. Arbitrary cages are explicitly out of scope for the MVP.

## Correspondence validation

At load time, before anything else, the app verifies the assumption and fails loudly
if it does not hold:

```
len(cage.points) == len(lowpoly.points)
```

If the counts differ, the app surfaces a clear error rather than producing a silently
wrong cage. This check is the guard that lets the rest of the math stay simple.

### FBX caveat

FBX (and assimp generally) frequently **splits vertices** along smoothing groups and
UV seams when loading. That reorders vertices and inflates the count, which breaks
correspondence. The loader requests no vertex splitting where the format allows it,
and the correspondence check above is the backstop. OBJ is the reliable interchange
path; FBX is supported but validated defensively.

## Displacement math

Two equivalent formulations, depending on whether the cage starts coincident with
the low poly or already offset.

Push from the low-poly base by an absolute amount:

```
cage.points = lowpoly.points + lowpoly_normals * value
```

Or nudge an already-offset cage by a delta:

```
cage.points += lowpoly_normals * delta
```

`lowpoly_normals` are unit vertex normals from `meshio` (PyVista `compute_normals`).

## Layering manual edits over the global slider

The displacement slider must not wipe out per-vertex edits the artist has made with
the gizmo. The cage position is therefore composed from three layers and recomputed
whenever the slider moves:

```
cage.points[i] = base[i] + normal[i] * slider_value + manual_delta[i]
```

- `base[i]` - low-poly vertex position.
- `normal[i] * slider_value` - the global outward push.
- `manual_delta[i]` - the accumulated per-vertex offset from gizmo edits (zero for
  untouched vertices).

`manual_delta` is a per-vertex array maintained by the editor. This is what lets the
artist set a global cage distance and then locally fix problem areas without the two
controls fighting each other.

## Hard vs soft normals (cage push must use soft)

The low poly and the cage consume normals for different purposes, and conflating
them tears the cage:

- **Hard normals stay on the low poly.** Splits at hard edges, UV seams, and
  smoothing-group boundaries are deliberate - the baked tangent-space normal map and
  tangent basis are authored against exactly those split normals. Never flatten them.
- **The cage push must use soft (welded) normals.** If the cage is peaked along the
  low poly's split normals, the coincident points at a seam fly apart in different
  directions, the shell tears, and bake rays leak through the gap (black spots /
  skirting). So compute the push direction by **fuse coincident positions ->
  recompute one averaged normal per welded position -> peak along that**. The cage
  stays watertight even over a hard-edged low poly.
- **Why this is legal:** the cage only decides where a ray starts and which way it
  fires; the low poly decides what normal/tangent is recorded at the hit. They are
  consumed at different bake stages, so a soft continuous cage (smooth, non-crossing
  ray directions across a seam) coexists with a hard low poly (sharp transition baked
  into the map).

Implementation note: the cage push uses `cage.soft_vertex_normals` (welds coincident
positions and averages the low poly's normals) - watertight over hard edges,
identical to the stored normals on a fully welded low poly. The low poly's hard
normals are kept on the editor (`hard_normals`) for the bake. The **skew** hard/soft
firing-direction blend is [Milestone 8 Phase 8.2](milestones/milestone-8/phase-2-skew-blend.md).

## Gizmo orientation

The per-vertex gizmo for vertex `i` is oriented to `lowpoly_normals[i]`. The default
interaction constrains motion to that single axis (the classic cage push: in/out
along the normal). `project_onto_normal(point, anchor, normal)` clamps an
arbitrary dragged position back onto the normal line, which is what enables a free
3-axis gizmo to fall back to constrained behavior. See `docs/interaction.md`.
