"""Headless tests for the smooth/relax brush and numeric vertex offset (feature-gap B)."""

from __future__ import annotations

import numpy as np
import pytest

from cagebakecake import meshio


def _strip_usd(tmp_path):
    # A 3x2 grid strip (6 verts) so a middle vertex has neighbours to relax toward.
    pts = np.array([[-1, 0, 0], [0, 0, 0.6], [1, 0, 0],
                    [-1, 1, 0], [0, 1, 0.6], [1, 1, 0]], dtype=float)
    faces = np.array([4, 0, 1, 4, 3, 4, 1, 2, 5, 4], dtype=np.int64)
    path = tmp_path / "low.usdc"
    meshio.save_mesh(str(path), pts, faces)
    return str(path)


@pytest.fixture
def editor(tmp_path):
    pytest.importorskip("pyvista")
    from cagebakecake.app import CageEditor
    try:
        return CageEditor(_strip_usd(tmp_path), off_screen=True)
    except Exception as exc:  # noqa: BLE001 - no headless GL context, etc.
        pytest.skip(f"headless render context unavailable: {exc}")


def test_adjacency_lists_triangle_neighbours():
    from cagebakecake.app import CageEditor
    ed = CageEditor.__new__(CageEditor)
    ed._adjacency = None
    ed._cached_low_tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)

    class _P:  # minimal stand-in for self.cage.points (only len is used)
        points = np.zeros((4, 3))
    ed.cage = _P()
    adj = ed._get_adjacency()
    assert set(adj[0].tolist()) == {1, 2, 3}   # vertex 0 touches all others
    assert set(adj[1].tolist()) == {0, 2}      # vertex 1 only in the first triangle


def test_smooth_brush_moves_cage_toward_neighbours(editor):
    before = editor.cage.points.copy()
    editor.set_smooth_strength(1.0)
    # Relax the whole strip: the raised middle row should drop toward its neighbours.
    editor.smooth_brush_at(editor.cage.points.mean(axis=0), radius=100.0)
    assert editor.manual_delta.any()
    assert not np.allclose(editor.cage.points, before)


def test_smooth_brush_is_mutually_exclusive(editor):
    editor.set_push_brush(True)
    editor.set_smooth_brush(True)
    assert editor._smooth_brush and not editor._push_brush and not editor._paint_skew
    editor.set_paint_skew(True)
    assert editor._paint_skew and not editor._smooth_brush


def test_selected_offset_round_trip(editor):
    assert editor.selected_offset() is None      # nothing selected
    editor._select(1)
    editor.set_selected_offset(0.25)
    assert editor.selected_offset() == pytest.approx(0.25, abs=1e-6)
    # The cage vertex moved along its normal by the offset.
    moved = editor.cage.points[1] - (editor.base[1] + editor.normals[1] * editor.global_push)
    np.testing.assert_allclose(moved, editor.normals[1] * 0.25, atol=1e-6)


def test_selected_offset_preserves_tangent_edit(editor):
    editor._select(1)
    n = editor.normals[1]
    # Add a purely tangential manual edit, then set the normal offset.
    tangent = np.cross(n, [1.0, 0.0, 0.0])
    tangent = tangent / np.linalg.norm(tangent)
    editor.manual_delta[1] = tangent * 0.1
    editor.set_selected_offset(0.3)
    # Tangential component preserved; normal component is now exactly 0.3.
    assert editor.manual_delta[1] @ n == pytest.approx(0.3, abs=1e-6)
    assert editor.manual_delta[1] @ tangent == pytest.approx(0.1, abs=1e-6)


def test_on_select_callback_fires(editor):
    seen = []
    editor._on_select = seen.append
    editor._select(2)
    editor._deselect()
    assert seen == [2, None]
