# Environment

What is known about the Python setup for this project, recorded from actual checks
on this machine (not assumptions).

## Interpreter

- **Python 3.14.3**, from
  `%LOCALAPPDATA%\Programs\Python\Python314\python.exe`.
- Project virtual environment lives at **`.venv/`** in the repo root (gitignored).

Recreate it:

```
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install numpy pyvista
```

## Confirmed working on Python 3.14

Installed and imported successfully (the earlier worry that VTK would lag 3.14 was
wrong - cp314 wheels exist):

| Package | Version |
| --- | --- |
| pyvista | 0.48.4 |
| vtk | 9.6.2 |
| numpy | 2.4.6 |

(pyvista pulls in matplotlib, pillow, pooch, etc. as transitive deps.)

## Mesh format support - the key constraint

Verified directly: **VTK ships no FBX importer** on this build
(`hasattr(vtk, 'vtkFBXImporter')` is `False`). So PyVista/VTK alone **cannot read
FBX**.

- Read natively via PyVista/VTK: OBJ, PLY, STL, VTK/VTP, and glTF/GLB (import path).
- **FBX read: solved for binary FBX via Blender, offline.** The runtime stays
  `pyvista` + `numpy`; Blender is a preprocess converter, not a runtime dependency.

## FBX conversion (decided: Blender-only)

Blender 4.3 (`C:\Program Files\Blender Foundation\Blender 4.3\blender.exe`) converts
FBX -> OBJ headless via `tools/blender_fbx_to_obj.py`. Blender's FBX importer is
production-grade and preserves topology, which is what cage correspondence needs.

```
"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe" --background --factory-startup ^
  --python tools\blender_fbx_to_obj.py -- assets\fbx\<name>.FBX assets\obj\<name>.obj
```

Verified working: `Mat Ball.FBX` -> 121,110 points; `Ada_FaceMesh.FBX` -> 386,544
points (~8 s); both load in pyvista via `pv.read(...)`.

**Limitation - ASCII FBX is unsupported.** Blender reads binary FBX only and errors
on ASCII FBX (`StageMic.fbx` is ASCII: header `; FBX 7.7.0 project file`). Fixes, in
order of preference: re-export the file as binary FBX from its source DCC, or (only
if ASCII support becomes a real requirement) adopt the `conda-forge` `assimp` CLI as
a single universal converter and drop Blender - do not run both tools.

**FBX write** is also unsupported, but the planned "create cage" button sidesteps it:
duplicating the source file byte-for-byte to `<name>_cage.fbx` needs no FBX writer,
and the identical copy guarantees matching vertex order when both are read back
through the same conversion (correspondence for free).

Open (defer past M1): is conversion a one-time preprocess (app reads OBJ only) or an
on-load step (app shells out to Blender)? This interacts with `create_cage` producing
`_cage.fbx` - decide where the convert happens before Milestone 2.

## USD path (evaluated - recommended internal format)

Switching the interchange format to USD is a **small, localized refactor**: format
I/O is isolated in `meshio.load_mesh`, and everything downstream (`cage.py`,
`bake.py`, `app.py`, gizmo, sliders) is format-blind. Only `meshio` and the
converter change.

Confirmed working on Python 3.14:

| Package | Version | Note |
| --- | --- | --- |
| usd-core | 26.5 | cp314 wheel exists; `pxr` (Usd, UsdGeom) imports and reads. |

- **Convert:** `tools/blender_to_usd.py` takes FBX **or** OBJ in and writes USD
  (`.usdc`) out via Blender. Same binary-only FBX limitation as the OBJ converter.
- **Read:** `usd-core` reads a `UsdGeom.Mesh`'s `points`, `faceVertexCounts`,
  `faceVertexIndices`, normals, and `st` UVs straight into numpy - exactly what
  `meshio` needs. No Blender at runtime.
- **USD topology is cleaner than OBJ.** MatBall reads as **20,315 shared vertices**
  in USD vs **121,110** per-corner points from pyvista's OBJ reader. Shared vertices
  are what cage correspondence wants, so USD is the better internal format.
- **Caveat - prim selection.** FBX LOD groups become multiple `Mesh` prims (e.g.
  `Ada_FaceMesh` exposes `..._LOD6` at 456 pts among others). `meshio` needs a rule
  for which prim to load (highest point count, or an explicit LOD0/name match, or a
  picker). Single-mesh assets like MatBall are unaffected.
- Verified reads: `MatBall.usdc` 20,315 pts / 40,370 faces; `MatBall_fromobj.usdc`
  identical; `Ada_FaceMesh.usdc` (LOD prim) 456 pts.

## Test assets

`assets/fbx/` contains: `Ada_FaceMesh.FBX` (~21 MB, dense organic, binary),
`Mat Ball.FBX` (binary), `StageMic.fbx` (ASCII - not loadable via Blender).
Converted OBJs land in `assets/obj/` (gitignored - derived artifacts).

## Notes

- Default `python` on PATH is 3.14; older interpreters (3.13, 3.12, 3.11, 3.10, 3.9,
  Anaconda) are also installed via the `py` launcher if a fallback is ever needed.
- See `docs/architecture.md` for the intended full dependency set
  (`pyvista`, `numpy`, `trimesh`, `imageio`, embree/assimp backends).
