"""Generate a synthetic low/high demo pair for the README app screenshots.

The meshes the original screenshots used are local-only (assets/usd is not in
git), so this fabricates a reproducible stand-in: a sculpted asteroid. Both
meshes share the same low-frequency silhouette (so the cage story reads); the
high poly adds bumps and craters the bake picks up. The low poly gets
faceVarying spherical UVs with the wrap seam fixed per-face so the bake doesn't
smear across it. Writes USD in the canonical frame meshio expects (metres,
Z-up, identity transform).

    python tools/make_demo_assets.py            # writes assets/usd/demo_{lp,hp}.usdc
    python tools/make_demo_assets.py <out_dir>  # writes somewhere else
"""

import os
import sys

import numpy as np
import pyvista as pv
from pxr import Usd, UsdGeom, Sdf, Vt

rng = np.random.default_rng(7)

# Deterministic detail kernels: gaussian bumps and crater dents on the unit sphere.
N_LOW_BLOBS, N_BUMPS, N_CRATERS = 6, 150, 18
low_dirs = rng.normal(size=(N_LOW_BLOBS, 3)); low_dirs /= np.linalg.norm(low_dirs, axis=1, keepdims=True)
low_amp = rng.uniform(0.10, 0.22, N_LOW_BLOBS) * rng.choice([-1, 1], N_LOW_BLOBS)
low_sharp = rng.uniform(2.0, 5.0, N_LOW_BLOBS)
bump_dirs = rng.normal(size=(N_BUMPS, 3)); bump_dirs /= np.linalg.norm(bump_dirs, axis=1, keepdims=True)
bump_amp = rng.uniform(0.02, 0.06, N_BUMPS)
bump_sharp = rng.uniform(60, 220, N_BUMPS)
crater_dirs = rng.normal(size=(N_CRATERS, 3)); crater_dirs /= np.linalg.norm(crater_dirs, axis=1, keepdims=True)
crater_amp = rng.uniform(0.04, 0.09, N_CRATERS)
crater_sharp = rng.uniform(25, 80, N_CRATERS)


def radius(dirs, detail):
    """Radial displacement field on unit directions."""
    r = np.ones(len(dirs))
    for d, a, s in zip(low_dirs, low_amp, low_sharp):
        r += a * np.exp(-s * (1 - dirs @ d))
    if detail:
        for d, a, s in zip(bump_dirs, bump_amp, bump_sharp):
            r += a * np.exp(-s * (1 - dirs @ d))
        for d, a, s in zip(crater_dirs, crater_amp, crater_sharp):
            g = np.exp(-s * (1 - dirs @ d))
            r -= a * g * (2 - g) * 1.4  # rimmed dent
    return r


def sculpt(nsub, detail):
    m = pv.Icosphere(radius=1.0, nsub=nsub)
    p = np.asarray(m.points, dtype=np.float64)
    d = p / np.linalg.norm(p, axis=1, keepdims=True)
    m.points = d * radius(d, detail)[:, None]
    return m


def spherical_uv_facevarying(mesh):
    """Per-corner spherical UVs; faces spanning the u wrap get the low side +1."""
    pts = np.asarray(mesh.points)
    d = pts / np.linalg.norm(pts, axis=1, keepdims=True)
    u = (np.arctan2(d[:, 1], d[:, 0]) / (2 * np.pi)) % 1.0
    v = np.arccos(np.clip(d[:, 2], -1, 1)) / np.pi
    faces = mesh.faces.reshape(-1, 4)[:, 1:]
    uv = np.stack([u, v], axis=1)[faces]           # (F, 3, 2)
    span = uv[..., 0].max(axis=1) - uv[..., 0].min(axis=1)
    wrap = span > 0.5
    fix = uv[wrap]
    fix[..., 0][fix[..., 0] < 0.5] += 1.0
    uv[wrap] = fix
    return uv.reshape(-1, 2), faces


def write_usd(path, mesh, uvs=None):
    pts = np.asarray(mesh.points, dtype=np.float64)
    faces = mesh.faces.reshape(-1, 4)[:, 1:]
    stage = Usd.Stage.CreateNew(path)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    m = UsdGeom.Mesh.Define(stage, "/demo")
    m.CreatePointsAttr([tuple(p) for p in pts])
    m.CreateFaceVertexCountsAttr([3] * len(faces))
    m.CreateFaceVertexIndicesAttr([int(i) for i in faces.ravel()])
    m.CreateExtentAttr([tuple(pts.min(axis=0)), tuple(pts.max(axis=0))])
    if uvs is not None:
        pv_api = UsdGeom.PrimvarsAPI(m.GetPrim())
        st = pv_api.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
                                  UsdGeom.Tokens.faceVarying)
        st.Set(Vt.Vec2fArray([tuple(x) for x in uvs]))
    stage.SetDefaultPrim(m.GetPrim())
    stage.GetRootLayer().Save()


high = sculpt(6, detail=True)
low = sculpt(2, detail=False)
uvs, _ = spherical_uv_facevarying(low)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "assets", "usd")
os.makedirs(out, exist_ok=True)
write_usd(os.path.join(out, "demo_hp.usdc"), high)
write_usd(os.path.join(out, "demo_lp.usdc"), low, uvs)
print(f"high: {high.n_points} pts  low: {low.n_points} pts  uvs: {len(uvs)}")
