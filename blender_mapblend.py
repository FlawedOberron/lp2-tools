# Blender headless: import every OBJ under a map's extracted _scr folder into one .blend.
#   flatpak run org.blender.Blender -b --python blender_mapblend.py -- SCR_DIR OUT.blend
import bpy, os, sys

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
for d, _, fs in sorted(os.walk(src)):
    for f in sorted(fs):
        if not f.endswith(".obj") or f.endswith(".col.obj"):  # collision: blender_collision.py
            continue
        before = set(bpy.data.objects)
        bpy.ops.wm.obj_import(filepath=os.path.join(d, f), forward_axis="NEGATIVE_Z", up_axis="Y",
                              global_scale=0.01)  # LP2 units are cm
        col = bpy.data.collections.new(f[:-4])
        bpy.context.scene.collection.children.link(col)
        for o in set(bpy.data.objects) - before:
            for c in o.users_collection:
                c.objects.unlink(o)
            col.objects.link(o)
# LP2 stores masks in texture alpha; the OBJ importer wires that to opacity
for mat in bpy.data.materials:
    if mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                for l in list(n.inputs["Alpha"].links):
                    mat.node_tree.links.remove(l)
                n.inputs["Alpha"].default_value = 1.0
bpy.ops.wm.save_as_mainfile(filepath=dst)
