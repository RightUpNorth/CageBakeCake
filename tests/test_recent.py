"""Headless tests for the recent-files MRU helper (feature-gap A)."""

from __future__ import annotations

import os

from cagebakecake import project


def test_mru_moves_to_front_and_dedups():
    recent = ["a.usd", "b.usd", "c.usd"]
    out = project.mru_add(recent, "b.usd")
    assert out[0] == "b.usd"
    assert out.count("b.usd") == 1
    assert out == ["b.usd", "a.usd", "c.usd"]


def test_mru_new_path_prepends():
    out = project.mru_add(["a.usd"], "new.usd")
    assert out == ["new.usd", "a.usd"]


def test_mru_caps_at_limit():
    recent = [f"{i}.usd" for i in range(8)]
    out = project.mru_add(recent, "new.usd", limit=8)
    assert len(out) == 8
    assert out[0] == "new.usd"
    assert "7.usd" not in out  # the oldest fell off


def test_mru_dedup_is_path_normalized():
    # The same file via two spellings collapses to one entry.
    a = os.path.join("dir", "x.usd")
    b = os.path.join("dir", ".", "x.usd")
    out = project.mru_add([a], b)
    assert len(out) == 1
