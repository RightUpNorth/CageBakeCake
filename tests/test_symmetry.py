"""Headless tests for symmetric editing and the push/inflate brush.

Covers the pure mirror math (cage.reflect_axis / cage.mirror_index) and, where a
headless render context is available, the editor's push brush + symmetry mirroring
through real geometry. See feature-gap B (cage editing power).
"""

from __future__ import annotations

import numpy as np
import pytest

from cagebakecake import cage, meshio


def test_reflect_axis_flips_one_component():
    np.testing.assert_allclose(cage.reflect_axis(np.array([1.0, 2.0, 3.0]), "x"),
                               [-1.0, 2.0, 3.0])
    arr = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    np.testing.assert_allclose(cage.reflect_axis(arr, "z"),
                               [[1.0, 2.0, -3.0], [4.0, 5.0, -6.0]])


def test_mirror_index_pairs_symmetric_vertices():
    # Symmetric about x = 0.
    pts = np.array([[-1, 0, 0], [1, 0, 0], [-1, 1, 0], [1, 1, 0]], dtype=float)
    m = cage.mirror_index(pts, "x")
    assert list(m) == [1, 0, 3, 2]


def test_mirror_index_marks_unmatched_as_minus_one():
    # bbox centre on x stays 0; (-1, 9) has no (1, 9) partner.
    pts = np.array([[-1, 0, 0], [1, 0, 0], [-1, 9, 0]], dtype=float)
    m = cage.mirror_index(pts, "x")
    assert list(m) == [1, 0, -1]


def _tiny_usd(tmp_path) -> str:
    # A 3x1 strip symmetric about x = 0: vertices at x = -1, 0, +1 (two rows).
    pts = np.array([[-1, 0, 0], [0, 0, 0], [1, 0, 0],
                    [-1, 1, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
    faces = np.array([4, 0, 1, 4, 3, 4, 1, 2, 5, 4], dtype=np.int64)
    path = tmp_path / "low.usdc"
    meshio.save_mesh(str(path), pts, faces)
    return str(path)


@pytest.fixture
def editor(tmp_path):
    pytest.importorskip("pyvista")
    from cagebakecake.app import CageEditor
    try:
        return CageEditor(_tiny_usd(tmp_path), off_screen=True)
    except Exception as exc:  # noqa: BLE001 - no headless GL context, etc.
        pytest.skip(f"headless render context unavailable: {exc}")


def test_apply_symmetry_mirrors_manual_delta():
    from cagebakecake.app import CageEditor
    ed = CageEditor.__new__(CageEditor)  # bypass the heavy mesh/render load
    ed.base = np.array([[-1, 0, 0], [1, 0, 0]], dtype=float)
    ed.manual_delta = np.zeros((2, 3))
    ed._symmetry = "x"
    ed._mirror = None
    ed._mirror_axis = None
    ed.manual_delta[0] = [0.2, 0.0, 0.5]
    ed._apply_symmetry(np.array([0]))
    # Vertex 0's mirror is vertex 1; the x component flips, the rest is copied.
    np.testing.assert_allclose(ed.manual_delta[1], [-0.2, 0.0, 0.5])


def test_apply_symmetry_off_is_noop():
    from cagebakecake.app import CageEditor
    ed = CageEditor.__new__(CageEditor)
    ed._symmetry = None
    ed.manual_delta = np.zeros((2, 3))
    ed.manual_delta[0] = [1.0, 0.0, 0.0]
    ed._apply_symmetry(np.array([0]))
    assert not ed.manual_delta[1].any()


def test_push_brush_inflates_region(editor):
    before = editor.cage.points.copy()
    # Push a wide brush at the left vertex; positive strength inflates along the normal.
    editor.set_push_strength(1.0)
    editor.push_brush_at(editor.cage.points[0], radius=10.0)
    assert editor.manual_delta.any()                     # some vertices moved
    assert not np.allclose(editor.cage.points, before)   # cage geometry changed


def test_push_brush_mirrors_with_symmetry(editor):
    editor.set_symmetry("x")
    editor.set_push_strength(1.0)
    # Brush only the left half (small radius around the x = -1 column).
    editor.push_brush_at(np.array([-1.0, 0.5, 0.0]), radius=0.6)
    md = editor.manual_delta
    moved = np.nonzero(np.any(md != 0.0, axis=1))[0]
    assert len(moved) > 0
    mirror = cage.mirror_index(editor.base, "x")
    for i in moved:
        j = mirror[i]
        if j >= 0 and j != i:
            np.testing.assert_allclose(md[j], cage.reflect_axis(md[i], "x"), atol=1e-9)
