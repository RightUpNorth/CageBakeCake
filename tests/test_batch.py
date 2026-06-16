"""Headless tests for the batch / CLI bake (no window, no GL).

batch.bake_pair and batch.bake_project bake straight from meshio + cage + bake, writing
PNGs without a PyVista plotter. See feature-gap G (batch / CLI bake).
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from cagebakecake import batch, project, recipe


def _uv_quad_usd(path, z=0.0):
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
def pair(tmp_path):
    pytest.importorskip("pxr")
    pytest.importorskip("trimesh")
    low = _uv_quad_usd(tmp_path / "low.usdc", z=0.0)
    high = _uv_quad_usd(tmp_path / "high.usdc", z=0.5)
    return low, high


def _shape(path):
    import imageio.v3 as iio
    return np.asarray(iio.imread(path)).shape


def test_bake_pair_writes_requested_maps(pair, tmp_path):
    low, high = pair
    out = tmp_path / "out"
    written = batch.bake_pair(low, high, out_dir=str(out), size=32, push=1.0,
                              ao_samples=8, maps=("normal", "ao", "curv"))
    names = sorted(os.path.basename(p) for p in written)
    assert names == ["low_ao.png", "low_curv.png", "low_normal.png"]
    for p in written:
        assert os.path.exists(p)
        assert _shape(p)[:2] == (32, 32)


def test_bake_pair_object_normal(pair, tmp_path):
    low, high = pair
    written = batch.bake_pair(low, high, out_dir=str(tmp_path / "o"), size=16, push=1.0,
                              maps=("objnormal",))
    assert [os.path.basename(p) for p in written] == ["low_objnormal.png"]


def test_bake_project_packs_recipe_outputs(pair, tmp_path):
    low, high = pair
    edits = project.encode_edits(1.0, np.zeros((4, 3)), 1.0, np.full(4, 1.0))
    edits.update(bake_size=[32, 32], supersample=1, padding=0, ao_samples=8,
                 explode=0.0, flip_green=False)
    rec = recipe.presets()["AO + Curvature"]  # one packed output from ao + curv
    doc = project.build_document(
        paths={"low": low, "high": high, "cage": None, "hdr": None},
        theme={"direction": "A", "mood": "light"}, recipe=rec, edits=edits)
    proj = tmp_path / "shot.cbcproj"
    project.save(str(proj), doc)

    out = tmp_path / "tex"
    written = batch.bake_project(str(proj), out_dir=str(out))
    assert len(written) == len(rec.outputs)
    for p in written:
        assert os.path.exists(p)
        assert _shape(p)[:2] == (32, 32)


def test_bake_pair_requires_uvs(tmp_path):
    pytest.importorskip("pxr")
    from cagebakecake import meshio
    # A mesh saved without UVs (meshio.save_mesh authors no `st`) cannot bake.
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    faces = np.array([4, 0, 1, 2, 3], np.int64)
    low = tmp_path / "nouv.usdc"
    meshio.save_mesh(str(low), pts, faces)
    high = _uv_quad_usd(tmp_path / "high.usdc", z=0.5)
    with pytest.raises(ValueError):
        batch.bake_pair(str(low), str(high), out_dir=str(tmp_path), size=16)
