"""Headless tests for the threaded-bake compute/apply split (no Qt thread).

The window runs `bake.bake` / `bake.bake_ao` on a worker thread, then applies the result
on the main thread. These tests exercise that boundary through a real CageEditor:
`bake_inputs` snapshots the pure-compute arguments, the pure bake runs synchronously here,
and `apply_bake_result` stores the maps and the incremental-rebake snapshot. Skipped when
no headless GL context is available. See feature-gap F (threaded bake).
"""

from __future__ import annotations

import numpy as np
import pytest

from cagebakecake import bake


def _uv_quad_usd(path, z=0.0):
    """A unit quad in the z=`z` plane carrying a faceVarying `st` UV layout (what the
    bake needs), authored directly so the test does not depend on asset files."""
    from pxr import Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    mesh = UsdGeom.Mesh.Define(stage, "/quad")
    mesh.CreatePointsAttr([(0, 0, z), (1, 0, z), (1, 1, z), (0, 1, z)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    st = UsdGeom.PrimvarsAPI(mesh.GetPrim()).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    st.Set([(0, 0), (1, 0), (1, 1), (0, 1)])
    stage.SetDefaultPrim(mesh.GetPrim())
    stage.GetRootLayer().Save()
    return str(path)


@pytest.fixture
def editor(tmp_path):
    pytest.importorskip("pyvista")
    low = _uv_quad_usd(tmp_path / "low.usdc", z=0.0)
    high = _uv_quad_usd(tmp_path / "high.usdc", z=0.5)
    from cagebakecake.app import CageEditor
    try:
        return CageEditor(low, high_path=high, off_screen=True)
    except Exception as exc:  # noqa: BLE001 - no headless GL context, etc.
        pytest.skip(f"headless render context unavailable: {exc}")


def test_bake_inputs_apply_round_trip(editor):
    editor.set_bake_size(32, 32)
    job = editor.bake_inputs()
    assert job is not None
    assert job["size"] == (32, 32)
    # The job snapshots the cage, so a later edit cannot corrupt a running bake.
    assert job["cage_snapshot"] is not editor.cage.points

    result = bake.bake(**job["kwargs"])           # what the worker thread runs (pure)
    assert editor.apply_bake_result(result, job) is True
    assert editor._baked_image is not None and editor._baked_image.shape == (32, 32, 3)
    assert editor._baked_miss is not None
    assert editor._face_miss is not None
    # The apply records the bake snapshot for an incremental re-bake.
    np.testing.assert_array_equal(editor._baked_cage_points, job["cage_snapshot"])


def test_apply_bake_cancelled_returns_false(editor):
    job = editor.bake_inputs()
    assert editor.apply_bake_result(None, job) is False   # cancelled bake
    assert editor._baked_image is None


def test_ao_inputs_apply_round_trip(editor):
    editor.set_bake_size(16, 16)
    editor.set_ao_samples(8)
    job = editor.ao_inputs()
    assert job is not None
    image = bake.bake_ao(**job["kwargs"])
    assert editor.apply_ao_result(image, job) is True
    assert editor._baked_ao is not None and editor._baked_ao.shape[:2] == (16, 16)


def test_inputs_none_without_high(tmp_path):
    pytest.importorskip("pyvista")
    low = _uv_quad_usd(tmp_path / "low.usdc")
    from cagebakecake.app import CageEditor
    try:
        ed = CageEditor(low, off_screen=True)  # no high poly
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"headless render context unavailable: {exc}")
    assert ed.bake_inputs() is None
    assert ed.ao_inputs() is None
