# Lost Planet 2 rModel -> Blender (armature, skinned meshes, UVs, materials).
#
# Headless:  flatpak run org.blender.Blender -b --python lp2_blender_import.py -- OUT.blend A.rModel [B.rModel ...]
# In Blender: run this script from the Text Editor after setting FILES below, or import
#             lp2_blender_import and call import_models([...]).
#
# Several parts (head/body/legs/back) imported together share ONE armature: bones are
# named by the game's global joint ID ("j008"), so the parts line up like in-game.
# Original per-model data needed for export is stored as custom properties.
import bpy, os, struct, sys
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mod2obj as M  # noqa: E402

SCALE = 0.01  # LP2 units are cm
# LP2 is Y-up; Blender is Z-up
AXIS = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def mat_from_lp2(f):
    # row-major, translation in [12:15] -> Blender column-major convention
    return Matrix([f[0:4], f[4:8], f[8:12], f[12:16]]).transposed()


def bind_world(bones):
    world = []
    for bn in bones:
        local = mat_from_lp2(bn["local"])
        world.append(local if bn["parent"] == 255 else world[bn["parent"]] @ local)
    return world


def get_armature(name="LP2_rig"):
    arm = bpy.data.objects.get(name)
    if arm is None:
        data = bpy.data.armatures.new(name)
        arm = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(arm)
        arm.show_in_front = True
    return arm


# Parts that own a joint come first when several parts define it differently
# (hd29xx puts j018, the forearm, somewhere else than the body does).
PART_PRIORITY = ("bd", "lg", "bk", "hd")


def part_rank(path):
    name = os.path.basename(path).lower()
    for n, pfx in enumerate(PART_PRIORITY):
        if name.startswith(pfx):
            return n
    return len(PART_PRIORITY)


def merge_skeletons(sources):
    """sources: [(path, bones)] -> {joint: (world Matrix, parent joint or None)}, one definition per
    joint: the position most parts agree on, ties broken by PART_PRIORITY."""
    seen = {}
    for path, bones in sources:
        world = bind_world(bones)
        for i, bn in enumerate(bones):
            parent = None if bn["parent"] == 255 else bones[bn["parent"]]["joint"]
            seen.setdefault(bn["joint"], []).append((part_rank(path), world[i], parent))
    merged = {}
    for joint, defs in seen.items():
        def key(d):
            pos = tuple(round(x) for x in d[1].translation)
            votes = sum(1 for o in defs if tuple(round(x) for x in o[1].translation) == pos)
            return (-votes, d[0])
        best = min(defs, key=key)
        merged[joint] = (best[1], best[2])
    return merged


def subtree_size(e):
    return 1 + sum(subtree_size(c) for c in e.children)


def build_armature(arm, merged):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for joint, (world, _parent) in sorted(merged.items()):
        e = eb.new(f"j{joint:03d}")
        head = (AXIS @ world).translation * SCALE
        e.head = head
        e.tail = head + Vector((0, 0, 0.03))
        e["lp2_joint"] = joint
    for joint, (_world, parent) in merged.items():
        if parent is not None and f"j{parent:03d}" in eb:
            eb[f"j{joint:03d}"].parent = eb[f"j{parent:03d}"]
    # aim each bone along its main chain (the child with the most descendants);
    # leaves continue their parent's direction
    for e in sorted(eb, key=lambda e: len(e.parent_recursive)):
        kids = [c for c in e.children if (c.head - e.head).length > 1e-3]
        if kids:
            e.tail = max(kids, key=lambda c: (subtree_size(c), (c.head - e.head).length)).head
        elif e.parent and (e.head - e.parent.head).length > 1e-3:
            d = e.head - e.parent.head
            e.tail = e.head + d.normalized() * max(0.03, min(d.length * 0.5, 0.1))
    bpy.ops.object.mode_set(mode="OBJECT")


def load_image(path):
    if not path or not os.path.exists(path):
        return None
    return bpy.data.images.load(path, check_existing=True)


def make_material(name, diffuse):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    img = load_image(diffuse)
    if img and not any(n.type == "TEX_IMAGE" for n in nt.nodes):
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])  # alpha is a mask, not opacity
    return mat


def resolve_tex(src, M_, slot):
    if not slot or slot > len(M_["texs"]):
        return None
    rel = M_["texs"][slot - 1].replace("\\", "/") + ".dds"
    root = M.find_tree_root(src)
    return (M.resolve_ci(root, rel) if root else None) or M.find_variant(src, rel)


def import_model(path, arm):
    b = open(path, "rb").read()
    Mdl = M.read_model(b)
    bones, _remap = M.read_bones(b)
    part = os.path.splitext(os.path.basename(path))[0]
    cols = {lvl: lod_part_collection(lvl, part) for lvl in LOD_LEVELS}
    mats = [make_material(f"{part}_mat{i:03d}", resolve_tex(path, Mdl, s[0])) for i, s in enumerate(Mdl["mats"])]
    for i, m in enumerate(mats):
        m["lp2_mat"] = i  # the exporter writes meshes back with this template material
    for k, m in enumerate(Mdl["meshes"]):
        # shadow meshes (on the untextured material, e.g. format 0cb6800e / db7da00d): the
        # exporter makes its own shadow copies, and re-exported as normal meshes they draw black
        if m["mat"] < len(Mdl["mats"]) and tuple(Mdl["mats"][m["mat"]]) == (0, 0, 0):
            continue
        g = M.mesh_geometry(b, m, Mdl)
        if g is None:
            continue
        verts, uvs, tris = g
        order = list(verts)
        index = {v: n for n, v in enumerate(order)}
        me = bpy.data.meshes.new(f"{part}_m{k:03d}")
        co = [(AXIS @ Vector(verts[i])) * SCALE for i in order]
        me.from_pydata(co, [], [tuple(index[i] for i in t) for t in tris])
        # the game's own normals: smooth where it shares vertices, hard where it split them
        base = Mdl["vb"] + m["voff"]
        nrm = [M.vertex_normal(b[base + (m["vbase"] + i) * m["stride"]:][:m["stride"]], m["fmt"]) for i in order]
        me.shade_smooth()
        if all(n is not None for n in nrm):
            me.normals_split_custom_set_from_vertices([(AXIS.to_3x3() @ Vector(n)).normalized() for n in nrm])
        if uvs:
            uvl = me.uv_layers.new(name="UVMap")
            for poly in me.polygons:
                for li in poly.loop_indices:
                    uvl.data[li].uv = uvs[order[me.loops[li].vertex_index]]
        me.materials.append(mats[m["mat"]] if m["mat"] < len(mats) else None)
        ob = bpy.data.objects.new(me.name, me)
        for lvl, bit in LOD_LEVELS.items():
            if m["lodmask"] & bit:
                cols[lvl].objects.link(ob)
        if not ob.users_collection:
            cols["Hi"].objects.link(ob)
        # keep what the exporter needs to rebuild this mesh entry
        ob["lp2_mesh_index"] = k
        ob["lp2_flags"] = m["lod"]
        ob["lp2_lodmask"] = m["lodmask"]
        ob["lp2_group"] = m["group"]
        ob["lp2_fmt"] = f"{m['fmt']:08x}"
        ob["lp2_source"] = path
        enc = M.SKIN.get(m["fmt"])
        if bones and enc:
            base = Mdl["vb"] + m["voff"]
            groups = {}
            for n, i in enumerate(order):
                v = b[base + (m["vbase"] + i) * m["stride"]:][:m["stride"]]
                for bi, w in M.vertex_skin(v, enc):
                    if bi >= len(bones):
                        continue
                    gname = f"j{bones[bi]['joint']:03d}"
                    if gname not in groups:
                        groups[gname] = ob.vertex_groups.new(name=gname)
                    groups[gname].add([n], w, "ADD")
            ob.parent = arm
            mod = ob.modifiers.new("Armature", "ARMATURE")
            mod.object = arm
    return Mdl


LOD_LEVELS = {"Hi": 0x01, "Med": 0x02, "Lo": 0xFC}  # mesh u32 @+4, bits 24-31


def lod_part_collection(level, part):
    """Top-level collection per LOD ("LOD Hi"), one child per part ("hd2900 Hi")."""
    top = bpy.data.collections.get(f"LOD {level}")
    if top is None:
        top = bpy.data.collections.new(f"LOD {level}")
        bpy.context.scene.collection.children.link(top)
    name = f"{part} {level}"
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        top.children.link(col)
    return col


def show_lod(level):
    """Eye-toggle every LOD collection off except `level`."""
    for lc in bpy.context.view_layer.layer_collection.children:
        if lc.name.startswith("LOD "):
            lc.hide_viewport = lc.name != f"LOD {level}"
            lc.collection.hide_render = lc.name != f"LOD {level}"


def import_models(paths, rig_name="LP2_rig"):
    arm = get_armature(rig_name)
    sources = []
    for p in paths:
        bones, _ = M.read_bones(open(p, "rb").read())
        if bones:
            sources.append((p, bones))
    if sources and not arm.data.bones:
        build_armature(arm, merge_skeletons(sources))
    for p in paths:
        import_model(p, arm)
    show_lod("Hi")
    return arm


if __name__ == "__main__" and "--" in sys.argv:
    argv = sys.argv[sys.argv.index("--") + 1:]
    out, srcs = argv[0], argv[1:]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_models(srcs)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print("LP2 saved", out)
