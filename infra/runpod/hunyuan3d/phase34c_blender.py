from __future__ import annotations
import sys
from pathlib import Path
import bpy

args = sys.argv[sys.argv.index("--") + 1 :]
source, target = map(Path, args[:2])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
for obj in list(bpy.context.scene.objects):
    if obj.type != "MESH":
        continue
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.000001)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.select_set(False)

bpy.ops.export_scene.gltf(
    filepath=str(target),
    export_format="GLB",
    export_apply=True,
    export_normals=True,
    export_texcoords=True,
    export_materials="EXPORT",
    export_yup=True,
)
