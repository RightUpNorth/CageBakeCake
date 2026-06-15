"""Mesh I/O tests (headless). Pins the cage-export round-trip: save_mesh writes a USD
in the canonical frame, and reading it back reproduces the same points and topology."""

from __future__ import annotations

import numpy as np

from cagebakecake import meshio


def _quad_grid():
    """A tiny 2x2-vertex quad: 4 points, one face. Flat VTK face array [4, 0,1,2,3]."""
    points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                       [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    faces = np.array([4, 0, 1, 2, 3], dtype=np.int64)
    return points, faces


def test_vtk_faces_to_usd_mixed_polygons():
    # A triangle then a quad: [3, 0,1,2, 4, 2,1,3,4]
    faces = np.array([3, 0, 1, 2, 4, 2, 1, 3, 4], dtype=np.int64)
    counts, indices = meshio._vtk_faces_to_usd(faces)
    assert list(counts) == [3, 4]
    assert list(indices) == [0, 1, 2, 2, 1, 3, 4]


def test_save_mesh_roundtrips_points_and_topology(tmp_path):
    points, faces = _quad_grid()
    out = tmp_path / "cage.usdc"
    meshio.save_mesh(str(out), points, faces)

    reloaded = meshio.load_mesh(str(out))
    assert np.allclose(reloaded.points, points, atol=1e-6)
    counts, indices = meshio._vtk_faces_to_usd(np.asarray(reloaded.faces))
    # Same single quad over the same four vertices (winding is orientation-only).
    assert list(counts) == [4]
    assert set(indices.tolist()) == {0, 1, 2, 3}


def test_save_mesh_canonical_frame_is_identity_on_read(tmp_path):
    # Points written in the canonical frame (metres, Z-up) must come back unchanged,
    # i.e. _to_canonical_frame is a no-op for our authored stage.
    points = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0],
                       [2.0, 3.0, 5.0], [0.0, 3.0, 5.0]])
    faces = np.array([4, 0, 1, 2, 3], dtype=np.int64)
    out = tmp_path / "frame.usdc"
    meshio.save_mesh(str(out), points, faces)
    reloaded = meshio.load_mesh(str(out))
    assert np.allclose(reloaded.points, points, atol=1e-6)
