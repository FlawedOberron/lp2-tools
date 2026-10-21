# Blender headless: build lp2_marker_assets.blend from build_marker_assets.py output.
#   flatpak run org.blender.Blender -b --python blender_marker_assets.py -- MARKERS_DIR OUT.blend [TEX_SIZE]
# One mesh per marker key ("LP2 asset vs_66"), top LOD only (mod2obj names objects ..._lodXX_..: bit 0x01),
# meshes without UVs (shadow / collision) dropped, LP2 Y-up cm -> Z-up metres (as the map blends), facing -Y.
# Base-colour textures are scaled down to TEX_SIZE (default 512) and packed, so the file stands alone.
# blender_lp2_map_markers.py uses these meshes when the file sits next to it (or is set in its preferences).
import bpy, json, os, re, sys
argv = sys.argv[sys.argv.index("--") + 1:]
root, out = argv[0], argv[1]
size = int(argv[2]) if len(argv) > 2 else 512
bpy.ops.wm.read_factory_settings(use_empty=True)
manifest = json.load(open(os.path.join(root, "manifest.json")))
done = {}
for key, rel in sorted(manifest.items()):
    if rel in done:  # several keys share a model (e.g. the post variants)
        me = done[rel].copy()
        me.name = f"LP2 asset {key}"
        me.use_fake_user = True
        continue
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=os.path.join(root, rel), global_scale=0.01, forward_axis="NEGATIVE_Z", up_axis="Y")
    new = [o for o in bpy.data.objects if o not in before]
    keep = []
    for o in new:
        m = re.search(r"_lod([0-9a-f]{2})_", o.name)
        if o.type != "MESH" or not o.data.uv_layers or (m and not int(m.group(1), 16) & 1):
            bpy.data.objects.remove(o)
        else:
            keep.append(o)
    if not keep:
        print(key, "nothing kept")
        continue
    ctx = {"active_object": keep[0], "selected_editable_objects": keep}
    with bpy.context.temp_override(**ctx):
        bpy.ops.object.join()
    ob = keep[0]
    ob.data.transform(ob.matrix_world)  # bake the import transform into the mesh
    me = ob.data
    me.name = f"LP2 asset {key}"
    me.use_fake_user = True
    bpy.data.objects.remove(ob)
    done[rel] = me
    print(key, len(me.vertices), "verts")
for img in bpy.data.images:
    if img.size[0] > size or img.size[1] > size:
        f = size / max(img.size)
        img.scale(max(1, int(img.size[0] * f)), max(1, int(img.size[1] * f)))
    img.pack()
for mat in bpy.data.materials:
    mat.use_fake_user = False
bpy.ops.outliner.orphans_purge(do_recursive=True)
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print("saved", out, len([m for m in bpy.data.meshes if m.name.startswith("LP2 asset")]), "meshes")
