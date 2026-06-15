# The core: what we are trying to achieve

The anchor for every other doc. When a feature, a UI change, or a roadmap item is in
question, it earns its place by serving the core below - or it waits. This is a draft
to align on; the open questions at the end are the parts still genuinely undecided.

## The problem

Bake cages have to be re-authored every time a high-poly or low-poly asset iterates,
and the tooling to do it is locked inside a specific DCC (Houdini/Dynamite, the
Substance/Marmoset bakers). There is no small, scriptable, DCC-independent place to
load the three meshes that matter, tune the cage, and bake - so cage work is either
trapped in a heavy host application or done blind.

## The core purpose

**A small, standalone, DCC-independent tool for authoring a bake cage and baking
against it - where the artist can see and trust what the cage is doing.**

Two words carry the weight:

- **Author** - not just *use* a cage someone else made, but shape it here: inflate it,
  fix poke-through locally, and get the edited cage back out.
- **See / trust** - the cage is an invisible envelope; the tool's job is to make it
  visible and to show whether it is doing its job (catching the right surface, missing
  nothing).

## The core loop

```
load (low + high [+ cage])
   -> inflate the cage globally
      -> fix problem areas locally (push/slide/skew the cage)
         -> bake (normal / AO / curvature), bounded by the cage
            -> inspect the result (in 3D and in 2D)
               -> adjust the cage and re-bake
                  -> export the cage and the maps
```

Everything in the product should make one step of this loop faster, clearer, or more
trustworthy. The loop is currently missing its first-class endpoints: **inspect in 2D**
(no bitmap viewer) and **export the cage** (only the map is exported). Closing those
two completes the loop end to end.

The `adjust -> re-bake` arrow is also the loop's hot path: a cage edit usually changes
a small region, so re-baking the whole map each pass is the main drag on iteration.
**Additive / incremental re-bake** - refreshing only the texels the edit touched - is a
core-loop accelerator, not a nice-to-have. (feature-gaps.md item C)

## Design principles (already in force)

1. **Headless math, thin GUI.** All geometry/bake logic is pure NumPy, UI-blind and
   unit-tested; the GUI is a replaceable shell. (architecture.md)
2. **Minimal dependencies.** PyVista/VTK + NumPy + trimesh + imageio + usd-core. No
   heavyweight runtime; offline converters stay offline.
3. **The viewport is the product.** The work is spatial; the panel serves the view.
4. **Smallest action that helps.** Surgical changes; do not restructure what is not
   broken. (CLAUDE.md working principles)

## What "good" looks like

- An artist opens a low/high pair, inflates the cage, fixes a few poke-through spots,
  bakes a clean tangent-space normal map, **sees the map in-app**, confirms there are
  no ray misses, and **exports both the cage and the map** - without opening a DCC.
- The same core runs headless for batch/CLI baking and for tests.

## Scope boundaries (what this is NOT)

- Not a general 3D modeller or sculptor - it edits a cage, not arbitrary geometry.
- Not a material/texture-painting tool - it bakes maps; it does not paint albedo.
- Not a renderer - PBR/HDR exist only to judge the surfaces, not to produce beauty
  shots.
- Not a format-conversion hub - USD is the runtime format; conversion is an offline
  preprocess.

## Decided

- **Cage export is in scope** (2026-06-15). Authoring is taken at face value: the
  edited cage must be exportable to USD, not just the baked maps. This confirms the
  README framing ("authoring and editing bake cages") and makes **cage save/load**
  (feature-gaps.md item A) the highest-priority gap - it is the missing half of the
  core purpose, not an add-on.

## Open questions to settle (these shape the roadmap)

1. **One UI surface or two?** Is the standalone PyVista path headless-only, or a
   supported interactive fallback that must keep parity with the Qt dock?
2. **How far does baking go?** MVP map set (normal/AO/curvature) only, or grow toward
   peer-tool breadth (ID, thickness, position, exploded bake)?
3. **Single-asset or batch?** Is GUI single-asset work the whole story, or is headless
   batch baking a first-class use case?
