"""Render a few off-screen viewport screenshots of CageBakeCake for the README / docs.

Loads the bundled bin low/high/cage assets, drives the CageEditor headlessly (no Qt
window) and captures: the cage over the high poly, the ray-miss diagnostic, the
auto-solved cage, and the baked normal map on the low poly. Run with the project venv:

    .venv\\Scripts\\python.exe tools\\make_screenshots.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pyvista as pv

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)  # run as a plain script from tools/ without installing the package

from cagebakecake import autocage
from cagebakecake.app import CageEditor

USD = os.path.join(HERE, "assets", "usd")
OUT = os.path.join(HERE, "screenshots")
SIZE = (1600, 1000)
THEME = "B-dark"


def _log(msg):
    print(f"[shots] {msg}", flush=True)


def _frame(ed, azimuth=35.0, elevation=20.0, zoom=1.35):
    """A consistent hero camera: isometric, nudged, zoomed in a touch."""
    ed.pl.view_isometric()
    ed.pl.camera.azimuth = azimuth
    ed.pl.camera.elevation = elevation
    ed.pl.reset_camera()
    ed.pl.camera.zoom(zoom)


def _cage_visible(ed, on):
    """Show/hide the translucent cage (surface + points + wireframe) so the low-poly
    diagnostic / normal-map shots are not occluded by it."""
    for attr in ("cage_actor", "_cage_pts_actor", "_cage_wire_actor"):
        actor = getattr(ed, attr, None)
        if actor is not None:
            actor.SetVisibility(on)


def _save(ed, name):
    path = os.path.join(OUT, name)
    ed.pl.render()
    ed.screenshot(path)
    _log(f"wrote {os.path.relpath(path, HERE)}")


def main():
    os.makedirs(OUT, exist_ok=True)
    low = os.path.join(USD, "bin_lp.usdc")
    high = os.path.join(USD, "bin_hp.usdc")
    cage = os.path.join(USD, "bin_lp_cage.usdc")
    hdr = os.path.join(USD, "textures", "color_121212.hdr")

    _log("loading editor (low + high + cage + hdr)...")
    ed = CageEditor(low, high_path=high, cage_path=cage,
                    hdr_path=hdr if os.path.exists(hdr) else None, off_screen=True)
    ed.pl.window_size = list(SIZE)
    try:
        ed.pl.enable_anti_aliasing("ssaa")
    except Exception:  # noqa: BLE001 - not fatal for a screenshot
        pass
    ed.set_theme(THEME)

    # 1) Hero: high poly shaded, cage translucent over it, low poly wireframe.
    _frame(ed)
    _save(ed, "01_cage_over_highpoly.png")

    # 2) Ray-miss diagnostic: deliberately pull the cage in tight so the high poly pokes
    #    through, bake, and colour the low faces by miss class (orange = poke-through / too
    #    tight, red = too loose). Low poly shaded grey behind it; cage + high hidden.
    _log("baking a deliberately-tight cage for the ray-miss overlay...")
    push0 = ed.global_push
    ed.global_push = ed._diag * 0.001          # very tight -> lots of poke-through
    ed._recompose()
    ed.set_bake_size(1024, 1024)
    ed._bake(resolution=1024)
    ed.set_high_visible(False)
    _cage_visible(ed, False)
    ed.set_low_style(True)                      # shaded grey, so the orange patches read
    ed.set_normal_map(False)
    ed.set_miss_overlay(True)
    _frame(ed)
    _save(ed, "02_ray_miss_overlay.png")

    # 3) Auto-solve the cage so it encloses the high poly, then show it hugging the form.
    ed.set_miss_overlay(False)
    ed.global_push = push0                      # back to the rest offset before solving
    ed._recompose()
    ed.set_low_style(False)                     # cage view: low poly back to wireframe
    ed.set_high_visible(True)
    _cage_visible(ed, True)
    _log("auto-solving the cage (probe + aim + verify)...")
    job = ed.autosolve_inputs(resolution=128)
    result = autocage.solve(**job["kwargs"], progress=lambda m: _log(f"  {m}"))
    ed.apply_autosolve_result(result, job)
    _frame(ed)
    _save(ed, "03_auto_solved_cage.png")

    # 4) The payoff: re-bake the solved cage and show the normal map lighting the low poly
    #    (cage + high hidden).
    _log("re-baking the solved cage...")
    ed._bake(resolution=1024)
    ed.set_high_visible(False)
    _cage_visible(ed, False)
    ed.set_low_style(True)        # shaded
    ed.set_normal_map(True)       # baked normal map on
    # A raking key light so the baked surface detail casts visible shading.
    center = ed.low.points.mean(axis=0)
    ed.pl.add_light(pv.Light(position=center + np.array([-1.3, 0.7, 1.4]) * ed._diag,
                             focal_point=center, color="white", intensity=1.15))
    _frame(ed, zoom=1.5)
    _save(ed, "04_baked_normal_map.png")

    _log("done")


if __name__ == "__main__":
    main()
