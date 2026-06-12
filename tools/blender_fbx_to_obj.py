"""Convert an FBX file to OBJ using Blender headless.

Run via Blender, not the project venv:

    blender --background --factory-startup --python tools/blender_fbx_to_obj.py -- <in.fbx> <out.obj>

Blender's FBX importer is production-grade and preserves topology, which is what the
cage workflow needs. The same deterministic conversion applied to a low poly and to
a byte-identical "_cage" copy yields identical vertex order, so cage<->low-poly
correspondence holds (see docs/cage-model.md).
"""

import sys
import bpy


def main():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("expected: ... --python this.py -- <in.fbx> <out.obj>")
    in_fbx, out_obj = argv[argv.index("--") + 1:][:2]

    # Start from an empty scene (remove the factory cube/camera/light).
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    bpy.ops.import_scene.fbx(filepath=in_fbx)

    # Export everything that was imported. Keep quads (no triangulation) so cage
    # topology is preserved; keep normals and UVs for shading and baking.
    bpy.ops.wm.obj_export(
        filepath=out_obj,
        export_selected_objects=False,
        export_uv=True,
        export_normals=True,
        export_materials=False,
        export_triangulated_mesh=False,
        apply_modifiers=True,
    )
    print(f"[convert] {in_fbx} -> {out_obj}")


if __name__ == "__main__":
    main()
