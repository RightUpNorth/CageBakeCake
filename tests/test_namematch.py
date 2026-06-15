"""Headless tests for the name-match pairing rule (no window, no mesh files).

The handoff rule: strip a trailing _lp/_hp (case-insensitive), lowercase, compare
bases. name_pairs() pairs each low part to a matching high part and reports the live
matched / no-match / manual status. CageEditor.__new__ bypasses the heavy mesh load -
name_pairs only reads low_parts / high_parts / _name_match.
"""

from __future__ import annotations

from cagebakecake.app import CageEditor, _base_name


def test_base_name_strips_lp_hp_suffix():
    assert _base_name("MatBall_lp") == "matball"
    assert _base_name("MatBall_hp") == "matball"
    assert _base_name("Lid_hp_v2") == "lid_hp_v2"   # only an exact trailing _hp strips
    assert _base_name("plain") == "plain"


def _editor(low, high, name_match):
    ed = CageEditor.__new__(CageEditor)
    ed.low_parts = [(n, None) for n in low]
    ed.high_parts = [(n, None) for n in high]
    ed._name_match = name_match
    return ed


def test_pairs_match_by_base_name():
    ed = _editor(["MatBall_lp", "Lid_lp"], ["MatBall_hp", "Lid_hp_v2"], True)
    rows = ed.name_pairs()
    assert rows[0]["low_name"] == "MatBall_lp" and rows[0]["high_name"] == "MatBall_hp"
    assert rows[0]["status"] == "matched"
    # Lid_lp (base 'lid') vs Lid_hp_v2 (base 'lid_hp_v2') -> no match
    assert rows[1]["low_name"] == "Lid_lp" and rows[1]["status"] == "no match"


def test_editing_name_makes_it_match():
    ed = _editor(["Lid_lp"], ["Lid_hp_v2"], True)
    assert ed.name_pairs()[0]["status"] == "no match"
    ed.rename_part("high", 0, "Lid_hp")
    assert ed.name_pairs()[0]["status"] == "matched"


def test_manual_when_name_match_off():
    ed = _editor(["MatBall_lp"], ["MatBall_hp"], False)
    assert ed.name_pairs()[0]["status"] == "manual"


def test_unpaired_high_part_gets_its_own_row():
    ed = _editor(["A_lp"], ["A_hp", "Extra_hp"], True)
    rows = ed.name_pairs()
    assert len(rows) == 2
    assert rows[1]["low"] is None and rows[1]["high_name"] == "Extra_hp"
