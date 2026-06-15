"""Programmatic viewport control - drive the editor like a user, headless.

CageEditor is UI-blind: the mouse/keyboard callbacks all bottom out in plain methods
(`_select`, `_deselect`, `_on_push`, `_bake`, ...). This wraps those in semantic actions
with timing and inspection helpers, so an interaction can be scripted, measured, and
evaluated without a window or a human - for performance work, regression checks, and
"dissect the viewport then evaluate" loops.

    c = ViewportController("low.usdc", high="high.usdc")
    c.select(100); c.deselect()
    c.stress_select_deselect(20)
    print(c.report())
    c.screenshot("frame.png")

Timing note: off-screen rendering captures the Python/VTK pipeline cost (gizmo build,
picking, recompose) faithfully, but not on-screen GPU present cost. Use it to compare
operations and find pipeline hotspots, not for absolute frame budgets.
"""

from __future__ import annotations

from time import perf_counter

import numpy as np

from .app import CageEditor


class ViewportController:
    def __init__(self, low, high=None, cage=None, hdr=None, off_screen=True):
        self.ed = CageEditor(low, high_path=high, cage_path=cage, hdr_path=hdr,
                             off_screen=off_screen)
        self.timings: list[tuple[str, float]] = []  # (action, milliseconds)
        self.ed.pl.render()  # prime a frame so picking/projection have a rendered scene

    # --- timing -------------------------------------------------------------
    def _timed(self, name: str, fn):
        t = perf_counter()
        result = fn()
        ms = (perf_counter() - t) * 1000.0
        self.timings.append((name, ms))
        return ms

    # --- actions (mirror the real mouse/keyboard interaction) ---------------
    def select(self, idx: int) -> float:
        return self._timed(f"select({idx})", lambda: self.ed._select(idx))

    def deselect(self) -> float:
        return self._timed("deselect", self.ed._deselect)

    def hover_vertex(self, idx: int) -> float:
        """Project cage vertex `idx` to screen and run the real hover path at that pixel."""
        x, y = self._project(self.ed.cage.points[idx])
        return self._timed(f"hover({idx})", lambda: self.ed._hover(x, y))

    def push(self, value: float) -> float:
        return self._timed(f"push({value:.4f})", lambda: self.ed._on_push(value))

    def set_skew(self, value: float) -> float:
        return self._timed(f"skew({value:.2f})", lambda: self.ed.set_skew(value))

    def move_vertex(self, idx: int, delta) -> float:
        """Apply a world-space offset to one cage vertex (the committed result of a drag),
        recomposing and following the gizmo as the interactive drag would."""
        def _do():
            self.ed.manual_delta[idx] = self.ed.manual_delta[idx] + np.asarray(delta, float)
            self.ed._recompose()
            self.ed._gizmo_follow()
            self.ed.pl.render()
        return self._timed(f"move_vertex({idx})", _do)

    def bake(self, resolution=1024) -> float:
        return self._timed(f"bake({resolution})",
                           lambda: self.ed._bake(resolution=resolution, progress=lambda _m: None))

    def orbit(self, azimuth=0.0, elevation=0.0) -> float:
        def _do():
            self.ed.pl.camera.azimuth += azimuth
            self.ed.pl.camera.elevation += elevation
            self.ed.pl.render()
        return self._timed(f"orbit({azimuth},{elevation})", _do)

    def render(self) -> float:
        return self._timed("render", self.ed.pl.render)

    # --- scenarios ----------------------------------------------------------
    def stress_select_deselect(self, n: int = 20) -> None:
        """Alternate select/deselect across `n` spread-out cage vertices - the interaction
        the user flagged as slow. Each op is timed into `self.timings`."""
        count = self.ed.cage.n_points
        for k in range(n):
            self.select(int(k * count / max(1, n)) % count)
            self.deselect()

    def select_internals(self, idx: int) -> dict:
        """Dissect one selection into its sub-steps (gizmo build / rebaseline / render),
        to see where select time goes."""
        ed = self.ed
        ed.selected = idx
        out = {}
        for name, fn in (("build_gizmo", lambda: ed._build_gizmo(idx)),
                         ("rebaseline", ed._rebaseline),
                         ("render", ed.pl.render)):
            t = perf_counter(); fn(); out[name] = (perf_counter() - t) * 1000.0
        return out

    # --- inspection ("dissect the viewport") --------------------------------
    def _project(self, world) -> tuple[int, int]:
        ren = self.ed.pl.renderer
        ren.SetWorldPoint(float(world[0]), float(world[1]), float(world[2]), 1.0)
        ren.WorldToDisplay()
        x, y, _z = ren.GetDisplayPoint()
        return int(x), int(y)

    def state(self) -> dict:
        ed = self.ed
        return {
            "selected": ed.selected,
            "cage_points": ed.cage.n_points,
            "high_points": None if ed.high is None else ed.high.n_points,
            "actors": sorted(ed.pl.actors.keys()),
            "gizmo_actors": sorted(ed._giz.keys()),
            "baked_maps": [n for n, _ in ed.baked_maps()],
            "camera_position": tuple(np.round(ed.pl.camera.position, 3)),
        }

    def screenshot(self, path: str) -> str:
        self.ed.pl.screenshot(path)
        return path

    def report(self) -> str:
        if not self.timings:
            return "no timed actions"
        groups: dict[str, list[float]] = {}
        for name, ms in self.timings:
            key = name.split("(")[0]
            groups.setdefault(key, []).append(ms)
        lines = ["action            count     avg ms     max ms"]
        for key in sorted(groups, key=lambda k: -sum(groups[k])):
            v = groups[key]
            lines.append(f"{key:<16} {len(v):>5} {sum(v)/len(v):>10.1f} {max(v):>10.1f}")
        return "\n".join(lines)
