# Blender headless: each OBJ -> its own .blend (textures packed, materials kept).
#   flatpak run org.blender.Blender -b --python blender_obj2blend.py -- OUT_DIR [--scale S] [--merge NAME] A.obj [B.obj ...]
# --scale: multiply every object (LP1 stages are in cm: 0.01 gives metres).
# --merge NAME: all OBJs into one NAME.blend, one collection per OBJ (stage pieces, sky, lava...).
import bpy, os, sys
argv = sys.argv[sys.argv.index("--") + 1:]
out, args = argv[0], argv[1:]
scale, merge, objs = 1.0, None, []
while args:
    a = args.pop(0)
    if a == "--scale":
        scale = float(args.pop(0))
    elif a == "--merge":
        merge = args.pop(0)
    else:
        objs.append(a)


def import_obj(path):
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=path)
    new = [ob for ob in bpy.data.objects if ob not in before]
    for ob in new:
        ob.scale = [s * scale for s in ob.scale]
        ob.location = [x * scale for x in ob.location]
    return new


def finish(name):
    # LP1/LP2 keep masks in texture alpha: not opacity, and not to be premultiplied into the colour
    for mat in bpy.data.materials:
        for n in (mat.node_tree.nodes if mat.node_tree else []):
            if n.type == "BSDF_PRINCIPLED":
                for l in list(n.inputs["Alpha"].links):
                    mat.node_tree.links.remove(l)
                n.inputs["Alpha"].default_value = 1.0
    for img in bpy.data.images:
        img.alpha_mode = "CHANNEL_PACKED"
    for ob in bpy.context.scene.objects:  # LP1 is Y-up like the OBJ; the importer already rotates to Z-up
        ob.select_set(False)
    if scale != 1.0:  # big scenes: let the viewport see the whole map
        for scr in bpy.data.screens:
            for area in scr.areas:
                for sp in area.spaces:
                    if sp.type == "VIEW_3D":
                        sp.clip_end = 10000.0
    try:
        bpy.ops.file.pack_all()
    except RuntimeError as e:
        print(f"{name}: pack failed: {e}")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, name + ".blend"), compress=True)
    print(f"saved {name}.blend")


if merge:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for path in objs:
        coll = bpy.data.collections.new(os.path.splitext(os.path.basename(path))[0])
        bpy.context.scene.collection.children.link(coll)
        for ob in import_obj(path):
            for c in ob.users_collection:
                c.objects.unlink(ob)
            coll.objects.link(ob)
    finish(merge)
else:
    for path in objs:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        import_obj(path)
        finish(os.path.splitext(os.path.basename(path))[0])
