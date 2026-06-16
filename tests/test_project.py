"""Headless tests for project / session persistence (no window).

Covers the pure edit encode/decode (sparse, mesh-size-tied), the document build/parse
+ JSON round-trip, path portability, and - when a headless render context is available -
a full round-trip through a real CageEditor. See cagebakecake/project.py.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from cagebakecake import meshio, project, recipe


def test_encode_is_sparse_and_round_trips():
    n = 5
    md = np.zeros((n, 3))
    md[2] = [0.1, 0.2, 0.3]
    md[4] = [-1.0, 0.0, 0.0]
    skew_map = np.full(n, 1.0)
    skew_map[1] = 0.25
    d = project.encode_edits(0.5, md, 1.0, skew_map)
    assert d["vertex_count"] == 5
    assert d["manual_delta"] == [[2, 0.1, 0.2, 0.3], [4, -1.0, 0.0, 0.0]]
    assert d["skew_map"] == [[1, 0.25]]  # only the deviation from the uniform skew

    push, md2, skew, sk2, matched = project.decode_edits(d, n)
    assert matched and push == 0.5 and skew == 1.0
    np.testing.assert_allclose(md2, md)
    np.testing.assert_allclose(sk2, skew_map)


def test_decode_vertex_mismatch_skips_per_vertex_but_keeps_scalars():
    d = project.encode_edits(0.3, np.eye(4, 3), 0.5, np.full(4, 0.5))
    push, md, skew, sk, matched = project.decode_edits(d, 6)  # different mesh
    assert not matched
    assert md.shape == (6, 3) and not md.any()       # per-vertex edits dropped
    assert skew == 0.5 and np.all(sk == 0.5)         # uniform skew default
    assert push == 0.3                               # scalar still applies


def test_decode_missing_push_is_none():
    push, *_ = project.decode_edits({"vertex_count": 3, "skew": 1.0}, 3)
    assert push is None


def test_document_json_round_trip(tmp_path):
    rec = recipe.presets()["Game-ready"]
    edits = project.encode_edits(0.1, np.zeros((3, 3)), 1.0, np.full(3, 1.0))
    doc = project.build_document(
        paths={"low": "a.usd", "high": None, "cage": None, "hdr": None},
        theme={"direction": "B", "mood": "dark"}, recipe=rec, edits=edits)
    path = tmp_path / "s.cbcproj"
    project.save(str(path), doc)
    back = project.load(str(path))
    assert back["paths"]["low"] == "a.usd"
    assert back["theme"] == {"direction": "B", "mood": "dark"}
    assert recipe.Recipe.from_dict(back["recipe"]).to_dict() == rec.to_dict()
    assert back["edits"] == doc["edits"]


def test_parse_rejects_foreign_document():
    with pytest.raises(ValueError):
        project.parse_document({"format": "something-else"})
    with pytest.raises(ValueError):
        project.parse_document([1, 2, 3])


def test_path_relativize_resolve_round_trip(tmp_path):
    base = str(tmp_path)
    inside = os.path.join(base, "mesh", "low.usd")
    rel = project.relativize(inside, base)
    assert not os.path.isabs(rel)
    assert os.path.normpath(project.resolve(rel, base)) == os.path.normpath(inside)
    assert project.relativize(None, base) is None  # absent path stays absent


def _tiny_usd(tmp_path) -> str:
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    faces = np.array([4, 0, 1, 2, 3], dtype=np.int64)
    path = tmp_path / "low.usdc"
    meshio.save_mesh(str(path), pts, faces)
    return str(path)


@pytest.fixture
def editor_factory(tmp_path):
    pytest.importorskip("pyvista")
    from cagebakecake.app import CageEditor

    low = _tiny_usd(tmp_path)

    def make():
        try:
            return CageEditor(low, off_screen=True)
        except Exception as exc:  # noqa: BLE001 - no headless GL context, etc.
            pytest.skip(f"headless render context unavailable: {exc}")

    return make


def test_editor_state_round_trips_through_a_fresh_editor(editor_factory):
    ed = editor_factory()
    ed.manual_delta[1] = [0.05, 0.0, 0.0]
    ed.global_push = 0.123
    ed.set_skew(0.4)
    ed.set_bake_size(2048, 1024)
    ed.set_supersample(2)
    ed.set_padding(8)
    ed.set_ao_samples(128)
    st = ed.authoring_state()

    ed2 = editor_factory()
    assert ed2.apply_authoring_state(st) is True
    np.testing.assert_allclose(ed2.manual_delta, ed.manual_delta)
    np.testing.assert_allclose(ed2.skew_map, ed.skew_map)
    assert ed2.global_push == 0.123
    assert ed2._bake_size == (2048, 1024)
    assert ed2._supersample == 2 and ed2._padding == 8 and ed2._ao_samples == 128
    # The restored cage is recomposed, not left at rest.
    np.testing.assert_allclose(ed2.cage.points, ed.cage.points)
