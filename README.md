# Cage Bake Cake

An interactive, standalone Python tool for authoring and editing **bake cages** -
the offset envelope used to project high-poly detail onto a low-poly mesh when
baking normal maps.

## Why

Bake cages have to be re-authored every time a high-poly or low-poly asset
iterates. Existing tooling is locked inside a specific DCC (for example, Dynamite
for Houdini). The goal here is a small, scriptable, DCC-independent app that loads
the three meshes that matter - **low poly**, **cage**, **high poly** - and lets an
artist tune the cage and bake directly, with minimal dependencies.

## What it does

1. Loads a low-poly, a cage, and a high-poly mesh together (OBJ and FBX).
2. Pushes the whole cage outward along normals with a float slider.
3. Sets cage transparency with a slider so the high poly shows through.
4. Picks individual cage vertices and nudges them with a gizmo oriented to the
   low-poly vertex normal, to fix poke-through or over-projection locally.
5. Shades the high poly with a simple PBR material lit by an HDR environment, with
   shift-drag to rotate the HDR ("move the light" by spinning the environment).
6. Bakes a tangent-space normal map from high to low poly, bounded by the cage.

## Status

Design phase. This repository currently contains design documentation only; no
implementation has been written yet. See `docs/` for the full design and
`docs/roadmap.md` for the planned build order.

## Planned quickstart (not yet implemented)

```
python -m cagebakecake low.obj cage.obj high.obj --hdr env.hdr
```

## Documentation

- `docs/environment.md` - Python interpreter, venv, confirmed package versions, FBX status.
- `docs/architecture.md` - tech stack and module layout.
- `docs/cage-model.md` - the cage data model and displacement math.
- `docs/interaction.md` - the viewport, sliders, gizmo, shader, and HDR controls.
- `docs/baking.md` - the normal-map bake algorithm.
- `docs/roadmap.md` - milestones, dependencies, and stretch goals.
