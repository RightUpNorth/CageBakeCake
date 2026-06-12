---
name: fbx-to-usd
description: Convert FBX or OBJ mesh assets to USD (.usdc) for CageBakeCake, using Blender headless. Use when the user has a new FBX/OBJ low/high/cage asset that needs to become USD so meshio.load_mesh can read it, asks to "convert <file> to usd", or drops bin_lp.fbx / bin_hp.fbx style source meshes into assets/fbx that the app cannot load yet. USD is the only format meshio reads at runtime.
---

# fbx-to-usd

CageBakeCake reads **USD** at runtime (`cagebakecake/meshio.py` -> `pxr`). VTK ships
no FBX importer, so FBX/OBJ source meshes must be converted to USD offline. This skill
picks the right converter and verifies the result:

- **Binary FBX / OBJ** -> `tools/blender_to_usd.py` via Blender headless (preserves
  topology, exports UVs + normals).
- **ASCII FBX** -> `tools/fbx_ascii_to_usd.py` via the venv Python (Blender's importer
  rejects ASCII FBX; this parses the geometry straight into USD - points, polygons,
  faceVarying normals, faceVarying `st` UVs - no Blender, no DCC round-trip).

Decide by header: a binary FBX begins `Kaydara FBX Binary`; an ASCII FBX begins
`; FBX <version> project file`. Check the first ~32 bytes before converting.

## When to use

- A new `.fbx` or `.obj` lands in `assets/fbx/` (e.g. `bin_lp.fbx`, `bin_hp.fbx`) and
  the app needs a matching `assets/usd/*.usdc`.
- The user says "convert X to USD", "make a usd from this fbx", or the app errors that
  it cannot open a non-USD mesh.

Do NOT use for FBX *writing* (unsupported - see `docs/environment.md`).

## Prerequisites

- For binary FBX / OBJ: Blender 4.3 at
  `C:\Program Files\Blender Foundation\Blender 4.3\blender.exe` (fall back to
  `Blender 3.5\blender.exe`). Confirm with `Test-Path` before running.
- For ASCII FBX: the project venv at `.venv\Scripts\python.exe` (has `pxr` + numpy).
- Run from the repo root so the `tools/` scripts resolve.

## Steps

1. **Resolve paths.** Input is the FBX/OBJ. Default output is
   `assets/usd/<input-stem>.usdc` (create `assets/usd/` if missing). Honor an explicit
   output path if the user gave one.

2. **Convert** with the converter matching the input (check the FBX header first).

   **Binary FBX / OBJ** - Blender headless (PowerShell call operator for the spaced
   Blender path):

   ```powershell
   & "C:\Program Files\Blender Foundation\Blender 4.3\blender.exe" --background `
     --factory-startup --python tools\blender_to_usd.py -- `
     "assets\fbx\<name>.fbx" "assets\usd\<name>.usdc"
   ```

   **ASCII FBX** - direct parser, no Blender:

   ```powershell
   & ".venv\Scripts\python.exe" tools\fbx_ascii_to_usd.py `
     "assets\fbx\<name>.fbx" "assets\usd\<name>.usdc"
   ```

   Large meshes are slow (e.g. `bin_hp.fbx` is multi-GB ASCII). For anything big, run
   in the background (`run_in_background: true`) rather than blocking, and report when
   done.

3. **Verify the output** loads and carries the data the bake needs. Use the venv
   Python (`.venv\Scripts\python.exe`), not global Python:

   ```python
   from pxr import Usd, UsdGeom
   stage = Usd.Stage.Open("assets/usd/bin_lp.usdc")
   # largest UsdGeom.Mesh, mirroring meshio._largest_mesh_prim
   m = max((UsdGeom.Mesh(p) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)),
           key=lambda mm: len(mm.GetPointsAttr().Get() or []))
   pts = m.GetPointsAttr().Get()
   st = UsdGeom.PrimvarsAPI(m.GetPrim()).GetPrimvar("st")
   print("points:", len(pts), "uv:", st.HasValue() if st else False)
   ```

   Report point count and whether `st` UVs are present. A **low poly destined for the
   bake must have UVs** (`st`); flag it loudly if it does not.

4. **Report** the output path, point count, face type, and UV presence. Do not commit
   the `.usdc` unless the user asks - converted assets may be gitignored derived
   artifacts (check `.gitignore`).

## Cage correspondence note

A cage is a byte-identical copy of the low poly run through the *same* conversion, so
vertex order matches (see `docs/cage-model.md`). If asked to make a cage, copy the low
FBX to `<name>_cage.fbx` first, then convert both - do not convert once and edit.

## References

- `tools/blender_to_usd.py` - the conversion implementation this skill drives.
- `docs/environment.md` - Blender path, binary-only FBX limitation, USD rationale.
