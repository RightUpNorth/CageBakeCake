"""Headless tests for the bake recipe data model and channel packing (no window).

Covers the recipe model (presets, JSON round-trip, name de-dup, removal clearing
referenced channels) and bake.pack_outputs (the pure RGBA channel compositing over
already-baked arrays). See docs/design/design_handoff_bake_recipe and recipe.py.
"""

from __future__ import annotations

import numpy as np

from cagebakecake import bake, recipe


def test_presets_build_with_independent_ids():
    ps = recipe.presets()
    assert set(ps) == {"Game-ready", "Hero asset", "AO + Curvature"}
    # Each preset's map ids are unique within it, and two presets never collide.
    all_ids = [m.id for r in ps.values() for m in r.bake_maps]
    assert len(all_ids) == len(set(all_ids))
    gr = ps["Game-ready"]
    assert [m.kind for m in gr.bake_maps] == ["normal", "ao", "curv", "cavity"]
    assert gr.bake_maps[0].space == "tangent"


def test_json_round_trip(tmp_path):
    r = recipe.presets()["Hero asset"]
    path = tmp_path / "hero.json"
    r.save(str(path))
    back = recipe.Recipe.load(str(path))
    assert back.to_dict() == r.to_dict()


def test_unique_name_dedups():
    r = recipe.Recipe("R")
    a = r.add_map("normal")
    b = r.add_map("normal")
    assert a.name == "Normal"
    assert b.name == "Normal 2"


def test_remove_map_clears_referenced_channels():
    r = recipe.presets()["Game-ready"]
    curv = next(m for m in r.bake_maps if m.kind == "curv")
    mask = next(o for o in r.outputs if o.file == "{LP}_mask")
    assert mask.ch["r"] == curv.id  # curvature packed into R
    r.remove_map(curv.id)
    assert curv.id not in {m.id for m in r.bake_maps}
    assert mask.ch["r"] is None     # reference cleared on removal


def test_resolve_filename_expands_lp_and_adds_extension():
    assert recipe.resolve_filename("{LP}_mask", "bin_lp") == "bin_lp_mask.png"


def _grey(h, w, v):
    return np.repeat(np.full((h, w, 1), v, np.uint8), 3, axis=2)


def test_pack_color_and_packed_outputs():
    r = recipe.presets()["Game-ready"]
    normal_id, ao_id, curv_id, _cavity = (m.id for m in r.bake_maps)
    h = w = 4
    baked = {
        normal_id: np.dstack([np.full((h, w), 10, np.uint8),
                              np.full((h, w), 20, np.uint8),
                              np.full((h, w), 250, np.uint8)]),
        ao_id: _grey(h, w, 200),
        curv_id: _grey(h, w, 130),
        # cavity intentionally absent -> its channel packs empty
    }
    files = bake.pack_outputs(baked, r, "matball_lp")
    assert set(files) == {"matball_lp_normal.png", "matball_lp_mask.png"}

    nrm = files["matball_lp_normal.png"]
    assert nrm.shape == (h, w, 4) and nrm.dtype == np.uint8
    # color: RGB from the normal map, alpha from AO
    assert nrm[0, 0].tolist() == [10, 20, 250, 200]

    mask = files["matball_lp_mask.png"]
    # packed: R=curvature, G=cavity(empty->0), B unassigned->0, A unassigned->255
    assert mask[0, 0].tolist() == [130, 0, 0, 255]


def test_pack_returns_empty_when_nothing_baked():
    assert bake.pack_outputs({}, recipe.presets()["AO + Curvature"], "x") == {}
