# Blender headless: add a map's collision (from sbc.py's *.col.obj) to an existing map .blend.
#   flatpak run org.blender.Blender -b MAP.blend --python blender_collision.py -- SCR_DIR OUT.blend
# Puts everything under a "Collision" collection: "Movement (atari...)" and "Bullets (tama...)",
# one object per collision group, one translucent colour per surface type (material names carry
# the surface type's flag word). Bullet collision starts hidden.
import bpy, os, sys

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
root = bpy.data.collections.get("Collision") or bpy.data.collections.new("Collision")
if root.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(root)
for d, _, fs in sorted(os.walk(src)):
    for f in sorted(fs):
        if not f.endswith(".col.obj"):
            continue
        name = f[:-8]
        label = ("Movement" if name.lower().startswith("atari") else "Bullets" if name.lower().startswith("tama") else "Other") + f" ({name})"
        before = set(bpy.data.objects)
        bpy.ops.wm.obj_import(filepath=os.path.join(d, f), forward_axis="NEGATIVE_Z", up_axis="Y", global_scale=0.01)
        col = bpy.data.collections.new(label)
        root.children.link(col)
        for o in set(bpy.data.objects) - before:
            for c in o.users_collection:
                c.objects.unlink(o)
            col.objects.link(o)
            o.display_type = "SOLID"
            o.hide_render = True
            o["lp2_collision"] = name
        if label.startswith("Bullets"):
            for lc in bpy.context.view_layer.layer_collection.children["Collision"].children:
                if lc.name == label:
                    lc.hide_viewport = True
# Translucent viewport colours from the OBJ material colours.
for mat in bpy.data.materials:
    if "_surf" in mat.name and mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                c = n.inputs["Base Color"].default_value
                mat.diffuse_color = (c[0], c[1], c[2], 0.45)
                n.inputs["Alpha"].default_value = 0.45
        mat.surface_render_method = "BLENDED" if hasattr(mat, "surface_render_method") else mat.surface_render_method
bpy.ops.wm.save_as_mainfile(filepath=dst)
print("LP2 saved", dst)
