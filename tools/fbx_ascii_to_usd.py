"""Convert an ASCII FBX mesh to USD (.usdc) without Blender.

Blender's FBX importer reads binary FBX only and errors on ASCII FBX (see
docs/environment.md). ASCII FBX is plain text, so for that case we parse the mesh
geometry directly into USD with `pxr` (already a runtime dependency via meshio).

    .venv\\Scripts\\python.exe tools/fbx_ascii_to_usd.py <in.fbx> <out.usdc>

Scope: the largest single Geometry node's points, polygons, ByPolygonVertex normals,
and ByPolygonVertex UVs (written as a faceVarying `st` primvar, matching the USD the
bake consumes). Node transforms are assumed identity (verified for the bin_* assets);
run the low poly, its cage copy, and the high poly through this same converter so they
stay mutually consistent (cage<->low correspondence; see docs/cage-model.md).
"""

from __future__ import annotations

import re
import sys

import numpy as np
from pxr import Sdf, Usd, UsdGeom, Vt

# Each is `<Name>: *<count> {` then an `a:` array (possibly wrapped) then `}`. We
# capture the FIRST occurrence of each - the primary Geometry node's arrays. The
# distinct token names keep Normals from matching Binormals/Tangents layers.
_WANTED = ("Vertices", "PolygonVertexIndex", "Normals", "UV", "UVIndex")
_HEADER = re.compile(r"^\s*(" + "|".join(_WANTED) + r"):\s*\*(\d+)\s*\{")


def _extract_arrays(path: str) -> dict[str, np.ndarray]:
    """Stream the file once, pulling the first occurrence of each wanted array.

    Streaming (rather than loading the whole file) keeps multi-GB ASCII FBX tractable;
    each array's numbers are parsed per line so no giant intermediate string is built.
    """
    out: dict[str, np.ndarray] = {}
    current: str | None = None
    chunks: list[np.ndarray] = []
    is_int = False

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if current is None:
                m = _HEADER.match(line)
                if m and m.group(1) not in out:
                    current = m.group(1)
                    chunks = []
                    is_int = current in ("PolygonVertexIndex", "UVIndex")
                continue
            # Inside a wanted array: accumulate until the closing brace.
            close = "}" in line
            body = line.split("}", 1)[0]
            body = body.split("a:", 1)[-1].strip().strip(",")
            if body:
                chunks.append(np.fromstring(body, sep=",",
                                            dtype=np.int64 if is_int else np.float64))
            if close:
                out[current] = (np.concatenate(chunks) if chunks
                                else np.array([], dtype=np.int64 if is_int else np.float64))
                current = None
                if len(out) == len(_WANTED):
                    break
    return out


def _decode_polygons(poly_index: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """FBX PolygonVertexIndex marks each polygon's last corner by bitwise-negating it
    (~i). Return (faceVertexCounts, faceVertexIndices) with positive indices."""
    ends = poly_index < 0
    indices = np.where(ends, ~poly_index, poly_index).astype(np.int64)
    end_pos = np.nonzero(ends)[0]
    starts = np.empty_like(end_pos)
    starts[0] = 0
    starts[1:] = end_pos[:-1] + 1
    counts = (end_pos - starts + 1).astype(np.int64)
    return counts, indices


def convert(in_path: str, out_path: str) -> None:
    a = _extract_arrays(in_path)
    if "Vertices" not in a or "PolygonVertexIndex" not in a:
        raise SystemExit(f"no mesh geometry found in {in_path}")

    points = a["Vertices"].reshape(-1, 3)
    counts, indices = _decode_polygons(a["PolygonVertexIndex"])
    n_corners = int(indices.size)

    stage = Usd.Stage.CreateNew(out_path)
    mesh = UsdGeom.Mesh.Define(stage, "/root/mesh")
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(counts.astype(np.int32)))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(indices.astype(np.int32)))

    # ByPolygonVertex normals (Direct) -> one per corner -> faceVarying.
    if "Normals" in a and a["Normals"].size == n_corners * 3:
        normals = a["Normals"].reshape(-1, 3).astype(np.float32)
        mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(normals))
        mesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)

    # ByPolygonVertex UVs (IndexToDirect) -> st primvar, faceVarying, one per corner.
    if "UV" in a and "UVIndex" in a and a["UVIndex"].size == n_corners:
        uv = a["UV"].reshape(-1, 2)
        st = uv[a["UVIndex"]].astype(np.float32)
        primvar = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
        )
        primvar.Set(Vt.Vec2fArray.FromNumpy(st))
        has_uv = True
    else:
        has_uv = False

    stage.GetRootLayer().Save()
    print(f"[convert] {in_path} -> {out_path}")
    print(f"  points={len(points)} polys={len(counts)} corners={n_corners} uv={has_uv}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: fbx_ascii_to_usd.py <in.fbx> <out.usdc>")
    convert(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
