"""Project / session persistence.

A project file (``*.cbcproj``, JSON) captures an authoring session so a cage edit
survives a restart and is resumable: the source mesh paths, the cage edits (global push
+ per-vertex manual delta), the skew map, the bake settings, the active recipe, and the
theme. It is plain JSON and UI-blind - MainWindow writes it from the editor + dock and
restores it on open.

Per-vertex arrays (manual_delta, skew_map) are tied to the loaded mesh's vertex count,
which is recorded and checked on load; a mismatch (the source mesh changed underneath
the project) skips just those arrays and keeps the rest of the session. Both arrays are
stored sparsely (only entries that differ from zero / the uniform skew), so an
otherwise-default cage with a handful of edits saves a handful of rows, not the whole
vertex set.

The pure encode/decode and document build/parse helpers carry no Qt or mesh
dependencies, so they are unit-tested headlessly (tests/test_project.py).
"""

from __future__ import annotations

import json
import os

import numpy as np

FORMAT = "cagebakecake-project"
VERSION = 1


# --- per-vertex edit encoding (pure, mesh-size-tied) -----------------------
def encode_edits(global_push, manual_delta, skew, skew_map) -> dict:
    """Sparse, JSON-able encoding of the cage edits. manual_delta -> its nonzero rows as
    [index, dx, dy, dz]; skew_map -> only entries that differ from the uniform skew as
    [index, value]. vertex_count pins the encoding to its mesh."""
    md = np.asarray(manual_delta, dtype=np.float64)
    nz = np.nonzero(np.any(md != 0.0, axis=1))[0]
    sk = np.asarray(skew_map, dtype=np.float64)
    dev = np.nonzero(sk != float(skew))[0]
    return {
        "vertex_count": int(len(md)),
        "global_push": float(global_push),
        "skew": float(skew),
        "manual_delta": [[int(i), *md[i].tolist()] for i in nz],
        "skew_map": [[int(i), float(sk[i])] for i in dev],
    }


def decode_edits(d: dict, n: int):
    """Inverse of encode_edits for a mesh of n vertices. Returns
    (global_push, manual_delta (n,3), skew, skew_map (n,), matched) where matched is False
    when the stored vertex_count != n - then the per-vertex arrays come back as a
    uniform-skew / zero-delta default (the scalars still apply). global_push is None when
    the document did not record one (keep the editor's default)."""
    skew = float(d.get("skew", 1.0))
    global_push = d.get("global_push")
    matched = int(d.get("vertex_count", -1)) == int(n)
    manual = np.zeros((n, 3), dtype=np.float64)
    skew_map = np.full(n, skew, dtype=np.float64)
    if matched:
        for i, dx, dy, dz in d.get("manual_delta", []):
            manual[int(i)] = (dx, dy, dz)
        for i, v in d.get("skew_map", []):
            skew_map[int(i)] = float(v)
    return global_push, manual, skew, skew_map, matched


# --- document build / parse ------------------------------------------------
def build_document(*, paths: dict, theme: dict, recipe, edits: dict) -> dict:
    """Assemble the full project document. `recipe` is a recipe.Recipe (or None);
    `paths`/`theme`/`edits` are already plain dicts."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "paths": dict(paths),
        "theme": dict(theme),
        "recipe": recipe.to_dict() if recipe is not None else None,
        "edits": dict(edits),
    }


def parse_document(data: dict) -> dict:
    """Validate a parsed document is a CageBakeCake project; return it unchanged."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a CageBakeCake project file")
    return data


# --- file IO ---------------------------------------------------------------
def save(path: str, document: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return parse_document(json.load(fh))


# --- path portability ------------------------------------------------------
def relativize(path, base):
    """Store a mesh path relative to the project dir when possible (so a project that
    sits next to its meshes is portable), else absolute (a different Windows drive)."""
    if not path:
        return path
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return os.path.abspath(path)


def resolve(path, base):
    """Resolve a stored path against the project dir - the inverse of relativize."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


# --- recent files (most-recently-used list) --------------------------------
def mru_add(recent, path, limit: int = 8) -> list:
    """Return a new most-recently-used list with `path` moved to the front, de-duplicated
    (case-insensitively on Windows via normcase) and capped at `limit`."""
    key = os.path.normcase(os.path.abspath(path))
    out = [path]
    for p in recent:
        if os.path.normcase(os.path.abspath(p)) != key:
            out.append(p)
    return out[:limit]
