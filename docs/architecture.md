# Architecture

## Design principle: headless math, thin GUI

All geometry and baking logic lives in pure, GUI-free modules that operate on NumPy
arrays. The interactive application is a thin layer on top that wires those
functions to PyVista widgets. This keeps the hard parts (correspondence,
displacement, baking) unit-testable without spawning a window, and makes the GUI
replaceable (a Qt front end can sit on the same core later).

## Tech stack

Minimal-dependency by design.

| Concern | Library | Notes |
| --- | --- | --- |
| Viewport, picking, widgets, opacity | **PyVista** (on VTK) | The single base library that covers rendering, multiple slider widgets, point picking, per-actor opacity, PBR shading, HDR environment textures, and access to raw VTK widgets. |
| Geometry math | **NumPy** | Displacement, correspondence, tangent bases. |
| FBX / glTF loading + ray casting | **trimesh** | Loads formats PyVista does not (assimp backend) and provides the BVH ray caster used for baking (`trimesh.ray.intersects_location`). |
| Bake speed | **embree** backend (`embreex` / `pyembree`) | Optional but strongly recommended; the pure-Python ray caster is slow on dense high-poly meshes. |
| HDR read + PNG write | **imageio** | Reads the `.hdr` equirectangular environment map and writes the baked normal-map PNG. |

OBJ, PLY, and STL load natively through PyVista (which also computes vertex normals
via `compute_normals`), so trimesh is pulled in only for FBX/glTF and for baking.

The MVP window uses a plain PyVista `Plotter`. A polished panelled desktop app
(`pyvistaqt` + `PySide6`, with a file menu and docked sliders) is the documented
upgrade path and is deferred to post-MVP.

## Module layout

```
cagebakecake/
  meshio.py     # load_mesh(path) -> vertices, faces, vertex_normals (NumPy)
                #   OBJ/PLY/STL via PyVista; FBX/glTF via trimesh + assimp.
                #   Wraps results into pyvista.PolyData; normalizes vertex normals.

  cage.py       # Headless cage math (no plotting):
                #   - validate_correspondence(lowpoly, cage)
                #   - displace(lowpoly_points, normals, value) -> cage points
                #   - project_onto_normal(point, anchor, normal)  (free-drag clamp)

  bake.py       # Headless tangent-space normal-map bake (no plotting):
                #   - rasterize low-poly UVs, cast rays low -> cage -> high (trimesh),
                #     encode high-poly normal into low-poly tangent space -> RGB array.

  app.py        # CageEditor: PyVista Plotter, three actors, sliders, picking, gizmo,
                #   PBR shading, HDR environment + shift-drag rotation, Bake button.

  __main__.py   # CLI: python -m cagebakecake low.obj cage.obj high.obj [--hdr env.hdr]
```

## Data flow

1. `__main__` parses the CLI and calls `meshio.load_mesh` for each mesh.
2. `app.CageEditor` validates cage-to-low-poly correspondence (`cage.validate_correspondence`),
   then registers three actors in the viewport.
3. Slider and gizmo callbacks call `cage.displace` / `cage.project_onto_normal` and
   write updated points back into the cage `PolyData`.
4. The Bake button calls `bake` with the current low poly, cage offset, and high
   poly, writes a PNG via `imageio`, and previews the result on the low poly.

See `docs/cage-model.md`, `docs/interaction.md`, and `docs/baking.md` for the
details of each stage.
