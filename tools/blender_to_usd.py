"""Convert an FBX or OBJ file to USD using Blender headless.

Run via Blender, not the project venv:

    blender --background --factory-startup --python tools/blender_to_usd.py -- <in.fbx|in.obj> <out.usdc>

Import is dispatched by extension; export is USD (extension decides .usd/.usda/.usdc).
Blender preserves topology, so the same deterministic conversion applied to a low
poly and to a byte-identical "_cage" copy yields identical vertex order, keeping
cage<->low-poly correspondence intact (see docs/cage-model.md).
"""

import os
import sys
import bpy


def main():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("expected: ... --python this.py -- <in.fbx|in.obj> <out.usdc>")
    in_path, out_usd = argv[argv.index("--") + 1:][:2]
    ext = os.path.splitext(in_path)[1].lower()

    # Start from an empty scene (remove the factory cube/camera/light).
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=in_path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=in_path)
    else:
        raise SystemExit(f"unsupported input extension: {ext}")

    bpy.ops.wm.usd_export(
        filepath=out_usd,
        selected_objects_only=False,
        export_uvmaps=True,
        export_normals=True,
        export_materials=False,
    )
    print(f"[convert] {in_path} -> {out_usd}")


if __name__ == "__main__":
    main()
