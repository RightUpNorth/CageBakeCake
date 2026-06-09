"""Headless cage math (no plotting).

The cage is assumed to be a topology-matched duplicate of the low poly: same vertex
count and order, so cage vertex i corresponds to low-poly vertex i and is pushed
along low-poly normal i. See docs/cage-model.md.
"""

from __future__ import annotations

import numpy as np


def validate_correspondence(low_points: np.ndarray, cage_points: np.ndarray) -> None:
    """Raise if the cage is not a vertex-for-vertex match of the low poly."""
    if len(low_points) != len(cage_points):
        raise ValueError(
            "cage/low-poly vertex count mismatch: "
            f"low={len(low_points)} cage={len(cage_points)} "
            "(cage must be a topology-matched duplicate; see docs/cage-model.md)"
        )


def displace(base_points: np.ndarray, normals: np.ndarray, value: float) -> np.ndarray:
    """Push base points outward along normals by a scalar value."""
    return base_points + normals * float(value)


def compose(
    base_points: np.ndarray,
    normals: np.ndarray,
    value: float,
    manual_delta: np.ndarray,
) -> np.ndarray:
    """Cage position = base + global normal push + per-vertex manual edits.

    This is the single composition both the displacement slider and the gizmo write
    through, so neither clobbers the other (see docs/cage-model.md).
    """
    return base_points + normals * float(value) + manual_delta


def project_onto_normal(
    point: np.ndarray, anchor: np.ndarray, normal: np.ndarray
) -> np.ndarray:
    """Clamp a freely-dragged point back onto the line through anchor along normal."""
    point = np.asarray(point, dtype=np.float64)
    anchor = np.asarray(anchor, dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    normal = normal / np.linalg.norm(normal)
    return anchor + normal * float(np.dot(point - anchor, normal))
