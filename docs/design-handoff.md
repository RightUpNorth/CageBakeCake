# Design-pass handoff

A snapshot of the application for a UX / visual-design review. It records what exists
today (every control, the interaction model, the visual language), what is fixed vs
malleable in the tech stack, and the open UX gaps a design pass should address. It is
descriptive, not prescriptive - the design decisions are the point of the pass.

## 1. What the app is

CageBakeCake is a standalone desktop tool for authoring and editing **bake cages** -
the offset envelope that bounds how high-poly detail projects onto a low-poly mesh
when baking normal maps. The user is a technical artist: loads a low poly, a high
poly, and (optionally) a cage; inflates and locally tweaks the cage; bakes a
tangent-space normal map (plus AO / curvature) bounded by that cage.

The whole job is **spatial and visual** - judging a translucent envelope against the
surfaces it wraps - so the viewport is the product and the panel is in service of it.

## 2. Tech stack (what a design pass can and cannot move)

| Concern | Library | Version | Design implication |
| --- | --- | --- | --- |
| Window shell, menus, docks, widgets | Qt via `qtpy` -> **PySide6** | - | Standard Qt widgets. Styling is QSS-themeable; custom widgets are possible but cost effort. |
| Viewport / render surface | **PyVista** (`pyvistaqt.QtInteractor`) on **VTK** | pyvista 0.48.4 / vtk 9.6.2 | The 3D view is VTK. In-viewport text/overlays are VTK actors, not HTML/CSS - layout control is coarse. |
| Geometry math | **NumPy** | 2.4.6 | Headless, UI-blind. Not a design surface. |
| Ray casting for bake | **trimesh** + **embree** | - | Backend only. |
| HDR read / PNG write | **imageio** | - | Backend only. |
| Mesh I/O | **usd-core** | 26.5 | USD only at runtime (`.usd/.usdc/.usda`). FBX/OBJ are converted to USD offline. |
| Interpreter | CPython | 3.14.3, `.venv/` | - |

**Architectural rule that protects the design (architecture.md): headless math, thin
GUI.** All geometry/bake logic is in pure NumPy modules (`cage.py`, `bake.py`,
`meshio.py`). The interactive core (`app.CageEditor`) is UI-blind, and the Qt shell
(`window.py`) is a thin layer of docks + menus over it. **The UI can be restyled or
restructured without touching the math.**

There are **two GUI surfaces** sharing that one core, which a design pass must
reconcile:

- **Qt window** (`window.py`, the default `python -m cagebakecake`) - menu bar +
  right-hand controls dock. This is the real app.
- **Standalone PyVista plotter** (`app.run`, `--no-qt`, and the `--screenshot`
  headless path) - the same viewport but with only two in-viewport slider widgets
  (offset, opacity) and a text help overlay. This is the headless / fallback path.

The two expose overlapping-but-different controls. Picking the canonical surface (or
deliberately scoping the plotter path to headless-only) is a design decision.

## 3. The viewport: the three actors and the visual language

| Actor | Default style | Color / material | Notes |
| --- | --- | --- | --- |
| High poly | PBR shaded, opaque | `tan`, metallic 0.15, roughness 0.5 | The detail source; what you bake from. Can be hidden. |
| Low poly | Wireframe | `white` lines; shaded mode = `lightgray` PBR, metallic 0.1, roughness 0.6 | The bake target. Shaded mode can carry the baked normal map. |
| Cage | Semi-transparent surface | `cyan`, opacity 0.35; `orange` vertex points (size 12, spheres); optional `cyan` wireframe | The editable envelope. |

Other viewport elements:

- **Background:** `slategray`. **Axes** widget bottom-corner.
- **Lighting:** an HDR environment texture if `--hdr` is given, else a **procedural
  sky** (cool top, warm ground, one broad sun) - so PBR always has image-based
  lighting. A movable key light provides the directional "sun" that shift-drag orbits.
- **Help overlay:** multi-line VTK text, font size 10, listing every keyboard shortcut.
- **Bake status:** VTK text, lower-right, `yellow`, font 9.
- **Soft-select region:** affected vertices drawn as `plasma`-colormapped spheres
  (weight 0..1).

The palette is currently functional-default, not designed - named CSS colors picked
for legibility while overlapping. **The visual language is wide open for the pass.**

## 4. The gizmo and interaction model

Selection and editing happen **in the viewport**, not the panel:

- **Select:** left-click a cage vertex (picks the nearest cage point). Hovering a
  vertex shows a white highlight sphere.
- **Gizmo** (custom, three grabbable handles at the selected vertex):
  - **Red arrow** along the vertex normal = displace along the normal (the classic
    cage push).
  - **Green ring** (lime, opacity 0.5) in the tangent plane = slide across the surface.
  - **Blue cube** (deepskyblue) = free 3-axis drag in the camera-facing plane.
  - Hovering a handle highlights it `yellow`. During a handle drag the camera is
    suppressed so the view does not tumble.
- **Deselect:** click empty space, or `[d]`.
- **Soft select** (proportional editing): pulls neighbours with a smooth falloff;
  radius adjustable; affected region visualized.
- **Shift + left-drag:** rotates the HDR / key light ("move the light").
- **Paint skew mode:** left-drag paints a per-region hard<->soft blend onto the mesh.

### Keyboard shortcuts (viewport)

`o` soft-select | `[` / `]` radius | `z` undo | `y` redo | `c` create-cage |
`b` bake | `h` hide high | `x` reset point | `X` reset cage | `l` low shading |
`L` high shading | `n` normal map | `k` cage points | `j` cage wireframe |
`v` LP normals | `d` deselect

(`create-cage`, `[c]`, duplicates the low-poly USD to `<stem>_cage.usd` - a
topology-matched cage. This is the only "save geometry" path; there is no cage export
in the menu.)

## 5. The controls dock (Qt) - the primary panel-design target

One right-hand `QDockWidget` ("Controls"), a single flat `QFormLayout` of ~25 widgets
in one ungrouped column, top to bottom:

1. **Cage offset** - slider + numeric label (global push along normals)
2. **Cage opacity** - slider (0-100%)
3. **Skew (hard..soft)** - slider + label (uniform firing-direction blend)
4. **Paint skew** - checkbox (left-drag paints)
5. **Brush skew** - slider + label (brush target value)
6. **Soft select** - checkbox
7. **Soft radius** - slider + label
8. **Low poly shaded** - checkbox
9. **Low poly wireframe** - checkbox (edge overlay)
10. **High poly visible** - checkbox
11. **High poly shaded** - checkbox
12. **High poly wireframe** - checkbox (edge overlay)
13. **Normal map (shaded low)** - checkbox
14. **Show LP normals** - checkbox (normal glyphs)
15. **Cage points** - checkbox
16. **Cage wireframe** - checkbox
17. **Name match** - checkbox (link low/high parts by prim name)
18. **Meshes** - per-prim visibility checklist (`QListWidget`)
19. **Bake width** / **Bake height** - dropdowns (256 .. 16384)
20. **Supersample** - dropdown (1x / 2x / 4x)
21. **Edge padding** - dropdown (0 .. 32 texels)
22. **AO samples** - dropdown (16 .. 256)
23. **Buttons:** Bake | Bake AO | Bake Curvature | Cancel bake | Reset Cage | Reset
    Selected Point
24. **Status** - wrapping label (mirrored to the window status bar)

Menu bar duplicates some of this: **File** (Open Low Poly, Open High Poly, Export
Normal Map, Quit) and **View** (the display toggles + Reset Cage / Reset Selected).

The dock has no grouping, no section headers, no separation of "edit the cage" from
"display" from "bake settings" from "actions". It is the clearest candidate for a
design pass: grouping, collapsible sections, progressive disclosure of the advanced
bake settings, and a clearer primary action.

## 6. Bake outputs and the missing bitmap viewer

Three bakes exist, all writing a PNG next to the low poly (or to a chosen path):

- **Normal map** (`<low>_normal.png`) - tangent-space; **previewed in 3D** by lighting
  it on the shaded low poly (toggle Normal map / Low poly shaded to compare).
- **AO** (`<low>_ao.png`) - hemisphere-sampled occlusion. **No in-app preview** - it
  only writes a file.
- **Curvature** (`<low>_curv.png`) - derived from the last normal bake. **No in-app
  preview** - it only writes a file.

**Gap: there is no 2D bitmap viewer.** The user cannot see the actual texture they
just baked without opening the PNG in an external program, and AO / curvature have no
preview at all. A docked or pop-out **image viewer** (show the last baked map, switch
between normal / AO / curvature, zoom/pan, maybe channel isolation) is a needed
feature and a natural home for bake feedback. This is the lead item for the next
build.

## 7. Known UX gaps and rough edges (input for the pass)

1. **No bitmap viewer** (section 6) - the headline gap.
2. **Default-asset bake fails:** the bundled Mat Ball low poly has **no UVs**, so a
   bake straight off the out-of-the-box defaults errors ("the low poly has no UVs").
   The bin asset has UVs and bakes fine. First-run impression is a failed bake. Fix
   options: ship a UV'd default, default to the bin pair, or disable the Bake button
   with a tooltip when UVs are absent.
3. **No cage export:** the only output is the baked map. Editing a cage and handing it
   back to a DCC is not possible (only `[c]` create-cage, which copies the *source*
   low poly, not the *edited* cage). Decide whether cage export is in scope.
4. **Two parallel control surfaces** (Qt dock vs in-viewport plotter sliders) expose
   different subsets - reconcile or scope.
5. **Flat ungrouped dock** of ~25 controls (section 5).
6. **Help is a static text overlay** in the viewport rather than a discoverable UI
   (tooltips, a shortcuts panel, on-hover hints).
7. **Menu / dock duplication** without an obvious source of truth.
8. **Three interactions are built but feel-unverified:** paint-skew feel, free-cube
   drag feel, and cancel-bake responsiveness (data layers are headless-tested; the
   in-hand feel has not been signed off).

## 8. How to run it

```
python -m cagebakecake                       # Qt window, default Mat Ball pair (no UVs - bake will warn)
python -m cagebakecake assets\usd\bin_lp.usdc --high assets\usd\bin_hp_nolid.usdc   # UV'd pair, bakes
python -m cagebakecake <low.usdc> --high <high.usdc> --cage <cage.usdc> --hdr <env.hdr>
python -m cagebakecake <low.usdc> --no-qt    # standalone pyvista window
python -m cagebakecake <low.usdc> --screenshot out.png   # headless render and exit
```

Use the project `.venv` interpreter (`.venv\Scripts\python.exe`).
</invoke>
