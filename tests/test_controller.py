"""ViewportController smoke tests (headless). Builds a tiny in-repo USD so it needs no
asset files, and skips if a headless render context is unavailable (CI without GL)."""

from __future__ import annotations

import numpy as np
import pytest

from cagebakecake import meshio


def _tiny_usd(tmp_path) -> str:
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    faces = np.array([4, 0, 1, 2, 3], dtype=np.int64)
    path = tmp_path / "low.usdc"
    meshio.save_mesh(str(path), pts, faces)
    return str(path)


@pytest.fixture
def controller(tmp_path):
    pytest.importorskip("pyvista")
    from cagebakecake.controller import ViewportController
    try:
        return ViewportController(_tiny_usd(tmp_path), off_screen=True)
    except Exception as exc:  # noqa: BLE001 - no headless GL context, etc.
        pytest.skip(f"headless render context unavailable: {exc}")


def test_select_then_deselect_is_timed(controller):
    controller.select(0)
    controller.deselect()
    names = [n for n, _ in controller.timings]
    assert any(n.startswith("select") for n in names)
    assert any(n == "deselect" for n in names)
    assert "no timed" not in controller.report()


def test_state_reports_geometry(controller):
    s = controller.state()
    assert s["cage_points"] == 4
    assert s["selected"] is None
    assert s["high_points"] is None  # no high poly passed


def test_select_updates_state(controller):
    controller.select(2)
    assert controller.ed.selected == 2
    assert controller.state()["gizmo_actors"]  # handles exist while selected
