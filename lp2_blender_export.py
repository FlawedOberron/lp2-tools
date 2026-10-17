# Blender -> Lost Planet 2 custom part models (.rModel), one per part collection.
#
# Headless:  flatpak run org.blender.Blender -b FILE.blend --python lp2_blender_export.py -- [OUTDIR] [LPC_name ...]
# In Blender: open this in the Text Editor and Run Script (exports every LPC_ collection to
#             //lp2_export next to the .blend).
#
# Scene layout (names are case-insensitive, Blender's ".001" suffixes are ignored):
#   LPC_<id>_<faction>_<display name>   one custom set, e.g. "LPC_scav01_ALL_Scavenger Kit";
#                            id: letters/digits; faction: RND FJ SPE NEV FF ALL; name: up to
#                            43 bytes, spaces fine. Several sets per scene are fine.
#     body | head | back | legs     part collections -> bd / hd / bk / lg
#       <name>               any mesh object: belt, bandolier... (part group 0)
#       <name>_g<NN>         explicit part group NN
#       hand_<pose>          hand pose: grip, open (both hands), fist, point, peace, thumb
#                            (the +X hand only); the side comes from where the hand is
# Meshes are skinned to LP2_rig (vertex groups jNNN = game joints). Bones not named jNNN are
# custom: each chain must hang off a joint the part already has; only bones carrying weight
# (and the links between them and the skeleton) are exported; ids are assigned once and
# stored on the bone as "lp2_joint". Only the high detail level is authored: every mesh is
# exported for all distances and gets a shadow copy. Materials, per material slot: the material's
# (or object's) custom property "lp2_mat" (template material index), else the importer's
# <part>_matNNN name, else the template's first textured material.
# The template (standard skeleton, materials, textures) is the part's original rModel:
# custom property "lp2_template" on the part or LPC collection, else the lp2_source of an
# imported object of that slot, else the 29xx (Femmes Fatales) part.
import bpy, bmesh, json, os, re, sys
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2model as L  # noqa: E402
import lp2tex  # noqa: E402

SLOTS = {"body": "bd", "head": "hd", "back": "bk", "legs": "lg"}
RAW = os.path.expanduser("~/Projects/lp2-assets/raw/CustomParts")
DEFAULT_TEMPLATE = RAW + "/{p}2900/model/hm/hm29/{p}2900/{p}2900.rModel"
HAND_POSES = {"grip": (200, 201), "open": (202, 203), "fist": (None, 204), "peace": (None, 205),
              "point": (None, 206), "thumb": (None, 207)}
JOINT_RE = re.compile(r"^j(\d{3})$")
SET_RE = re.compile(r"^LPC_([A-Za-z0-9]+)_([A-Za-z]+)_(.+)$", re.I)
# faction code -> the game's faction byte (None = generic, offered to every faction)
FACTIONS = {"RND": 0, "FJ": 1, "SPE": 2, "NEV": 3, "FF": 4, "ALL": None}
FACTION_NAMES = {"RND": "Rounders", "FJ": "Fight Junkies", "SPE": "Snow Pirate Elites",
                 "NEV": "NEVEC Black Ops", "FF": "Femmes Fatales", "ALL": "any faction"}
NAME_MAX_BYTES = 43  # sname.bin display-name limit


def base_name(n):
    return re.sub(r"\.\d{3}$", "", n)


def to_lp2(v):
    # Blender (m, Z-up) -> LP2 (cm, Y-up); inverse of the importer's AXIS
    return (v.x * 100.0, v.z * 100.0, -v.y * 100.0)


def dir_to_lp2(v):
    return (v.x, v.z, -v.y)


# ---------------------------------------------------------------- scene discovery

def find_sets(names=None):
    out = []
    for c in bpy.data.collections:
        n = base_name(c.name)
        if n.lower().startswith("lpc_") and (not names or c.name in names or n in names):
            out.append(c)
    return out


def parse_set_name(root):
    """LPC_<id>_<faction>_<display name> -> (id, faction code, display name)."""
    m = SET_RE.match(base_name(root.name))
    if not m:
        raise L.ExportError(f"'{root.name}': name it LPC_<id>_<faction>_<display name>, e.g. "
                            "LPC_scav01_ALL_Scavenger Kit (id: letters/digits only; factions: "
                            + ", ".join(FACTIONS) + ")")
    sid, fac, name = m.group(1), m.group(2).upper(), m.group(3).strip()
    if fac not in FACTIONS:
        raise L.ExportError(f"{root.name}: unknown faction code '{fac}' (use {', '.join(FACTIONS)})")
    if not name or len(name.encode("utf-8")) > NAME_MAX_BYTES:
        raise L.ExportError(f"{root.name}: display name must be 1-{NAME_MAX_BYTES} bytes")
    if not name.isprintable():
        raise L.ExportError(f"{root.name}: display name has control characters")
    return sid, fac, name


def part_collections(root):
    parts = {}
    for c in root.children:
        key = base_name(c.name).lower()
        if key in SLOTS:
            if SLOTS[key] in parts:
                raise L.ExportError(f"{root.name}: two '{key}' collections")
            parts[SLOTS[key]] = c
    return parts


def template_path(root, part_col, prefix):
    for c in (part_col, root):
        p = c.get("lp2_template")
        if p:
            return bpy.path.abspath(p), None
    for o in part_col.all_objects:
        src = o.get("lp2_source")
        if src and os.path.basename(src).lower().startswith(prefix):
            return src, None
    for o in bpy.data.objects:
        src = o.get("lp2_source")
        if src and os.path.basename(src).lower().startswith(prefix):
            return src, f"template from another set in this file: {os.path.basename(src)}"
    p = DEFAULT_TEMPLATE.format(p=prefix)
    return p, f"no template set, using {os.path.basename(p)}"


def armature_of(obj):
    for m in obj.modifiers:
        if m.type == "ARMATURE" and m.object:
            return m.object
    if obj.parent and obj.parent.type == "ARMATURE":
        return obj.parent
    return None


# ---------------------------------------------------------------- meshes

def object_group(obj, centre_x, warn):
    if "lp2_group" in obj:
        return int(obj["lp2_group"])
    n = base_name(obj.name).lower()
    m = re.match(r"^hand_([a-z]+)", n)
    if m:
        pose = m.group(1)
        if pose not in HAND_POSES:
            raise L.ExportError(f"{obj.name}: unknown hand pose '{pose}' (use {', '.join(HAND_POSES)})")
        neg, pos = HAND_POSES[pose]
        g = neg if centre_x < 0 else pos
        if g is None:
            raise L.ExportError(f"{obj.name}: pose '{pose}' only exists for the +X hand")
        return g
    m = re.search(r"_g(\d+)$", n)
    return int(m.group(1)) if m else 0


MAT_NAME_RE = re.compile(r"_mat(\d+)(?:\.\d+)?$")  # the importer's names: body_mat003(.001)


def slot_material(obj, slot, tpl):
    """Template material index for one material slot of obj: the material's (or object's)
    "lp2_mat" property, else the importer's <part>_matNNN name, else the template's first
    textured material."""
    mat = obj.material_slots[slot].material if slot < len(obj.material_slots) else None
    for src in (mat, obj):
        if src is not None and "lp2_mat" in src:
            i = int(src["lp2_mat"])
            if not 0 <= i < len(tpl["mats"]):
                raise L.ExportError(f"{obj.name}: lp2_mat {i} out of range (template has {len(tpl['mats'])})")
            return i
    m = MAT_NAME_RE.search(mat.name) if mat is not None else None
    if m and int(m.group(1)) < len(tpl["mats"]):
        return int(m.group(1))
    for i, tm in enumerate(tpl["mats"]):
        if tm["slots"] != (0, 0, 0):
            return i
    return 0


def subset(verts, tris):
    """The vertices the given triangles use, with the triangles renumbered."""
    remap, out = {}, []
    for t in tris:
        for i in t:
            if i not in remap:
                remap[i] = len(out)
                out.append(verts[i])
    return out, [tuple(remap[i] for i in t) for t in tris]


def mesh_data(obj, joint_of_group):
    """-> (verts, tris, tri_slots) in LP2 space; verts split where normals/UVs/tangent sign
    differ; tri_slots = each triangle's material slot."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    src = ev.to_mesh()
    try:
        bm = bmesh.new()
        bm.from_mesh(src)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        me = bpy.data.meshes.new("_lp2_export_tmp")
        bm.to_mesh(me)
        bm.free()
    finally:
        ev.to_mesh_clear()
    try:
        has_uv = len(me.uv_layers) > 0
        if has_uv:
            me.calc_tangents(uvmap=me.uv_layers.active.name)
        uvl = me.uv_layers.active.data if has_uv else None
        normals = me.corner_normals if hasattr(me, "corner_normals") else None
        mw = obj.matrix_world
        nmat = mw.to_3x3().inverted().transposed()
        verts, key_index, tris, tri_slots = [], {}, [], []
        weights_cache = {}
        for poly in me.polygons:
            tri = []
            for li in poly.loop_indices:
                loop = me.loops[li]
                vi = loop.vertex_index
                n = (normals[li].vector if normals is not None else loop.normal)
                n = (nmat @ n).normalized()
                uv = tuple(uvl[li].uv) if has_uv else (0.0, 0.0)
                if has_uv:
                    t = (mw.to_3x3() @ loop.tangent).normalized()
                    sign = loop.bitangent_sign
                else:
                    t = n.orthogonal().normalized()
                    sign = 1.0
                key = (vi, round(n.x, 4), round(n.y, 4), round(n.z, 4), round(uv[0], 5), round(uv[1], 5), sign)
                k = key_index.get(key)
                if k is None:
                    if vi not in weights_cache:
                        ws = []
                        for g in me.vertices[vi].groups:
                            j = joint_of_group.get(g.group)
                            if j is not None and g.weight > 0:
                                ws.append((j, g.weight))
                        if not ws:
                            raise L.ExportError(f"{obj.name}: vertex {vi} has no weights on any bone")
                        weights_cache[vi] = ws
                    k = key_index[key] = len(verts)
                    verts.append(dict(pos=to_lp2(mw @ me.vertices[vi].co), normal=dir_to_lp2(n),
                                      tangent=dir_to_lp2(t) + (sign,), uv=uv, weights=weights_cache[vi]))
                tri.append(k)
            tris.append(tuple(tri))
            tri_slots.append(poly.material_index)
        return verts, tris, tri_slots
    finally:
        bpy.data.meshes.remove(me)


def split_pieces(verts, tris, limit=L.MAX_RUN_VERTS):
    """Greedy split of one mesh into pieces of at most `limit` vertices."""
    if len(verts) <= limit:
        return [(verts, tris)]
    pieces, cur_v, cur_map, cur_t = [], [], {}, []
    for t in tris:
        new = [i for i in t if i not in cur_map]
        if len(cur_v) + len(new) > limit:
            pieces.append((cur_v, cur_t))
            cur_v, cur_map, cur_t = [], {}, []
        for i in t:
            if i not in cur_map:
                cur_map[i] = len(cur_v)
                cur_v.append(verts[i])
        cur_t.append(tuple(cur_map[i] for i in t))
    if cur_t:
        pieces.append((cur_v, cur_t))
    return pieces


# ---------------------------------------------------------------- bones

def custom_bones_for(arm, tpl, used_names, set_name, warnings):
    """Custom bones (non-jNNN) this part needs: weighted ones, their ancestors and their
    descendants. Assigns and stores lp2_joint ids. -> list for lp2model, {name: joint}."""
    std = {b["joint"] for b in tpl["bones"]}
    bones = arm.data.bones
    custom = [b for b in bones if not JOINT_RE.match(b.name)]
    if len(custom) > L.MAX_CUSTOM_BONES:
        raise L.ExportError(f"{arm.name}: {len(custom)} custom bones (cap {L.MAX_CUSTOM_BONES})")
    # weighted bones plus the unweighted links between them and the part's skeleton
    need = set()
    for name in used_names:
        b = bones[name]
        while b is not None and not JOINT_RE.match(b.name):
            need.add(b.name)
            b = b.parent
    # ids: keep stored ones, then hand out free ones from the top (game chains use < 190)
    taken = {b["joint"] for b in tpl["bones"]} | {int(b["lp2_joint"]) for b in custom if "lp2_joint" in b}
    out, ids = [], {}
    for b in sorted((bones[n] for n in need), key=lambda b: len(b.parent_recursive)):
        if "lp2_joint" not in b:
            free = next((i for i in range(254, 0, -1) if i not in taken), None)
            if free is None:
                raise L.ExportError("no free joint ids left")
            b["lp2_joint"] = free
            taken.add(free)
        j = int(b["lp2_joint"])
        p = b.parent
        if p is None:
            raise L.ExportError(f"custom bone {b.name} has no parent; parent it to a jNNN joint of this part")
        if JOINT_RE.match(p.name):
            pj = int(JOINT_RE.match(p.name).group(1))
            if pj not in std:
                raise L.ExportError(f"custom bone {b.name} hangs off {p.name}, which this part does not have "
                                    f"(it has {', '.join(f'j{x:03d}' for x in sorted(std))})")
        else:
            pj = int(p["lp2_joint"])
        ids[b.name] = j
        out.append(dict(name=b.name, joint=j, parent=pj,
                        world=to_lp2(arm.matrix_world @ b.head_local)))
    return out, ids


# ---------------------------------------------------------------- export

def export_part(root, prefix, col, outdir, shadow=True):
    warnings = []
    tpath, w = template_path(root, col, prefix)
    if w:
        warnings.append(w)
    if not os.path.exists(tpath):
        raise L.ExportError(f"template not found: {tpath}")
    tpl = L.read_template(open(tpath, "rb").read())
    std = {b["joint"] for b in tpl["bones"]}
    objs = [o for o in col.all_objects if o.type == "MESH" and not o.hide_render]
    if not objs:
        raise L.ExportError(f"{root.name}/{col.name}: no mesh objects")
    arms = {armature_of(o) for o in objs}
    if None in arms:
        bad = [o.name for o in objs if armature_of(o) is None]
        raise L.ExportError(f"not skinned to an armature: {', '.join(bad)}")
    if len(arms) > 1:
        raise L.ExportError(f"{col.name}: meshes use different armatures ({', '.join(a.name for a in arms)})")
    arm = arms.pop()

    pose_pos = arm.data.pose_position
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    try:
        meshes = []
        for o in sorted(objs, key=lambda o: o.name):
            jog = {}
            for g in o.vertex_groups:
                m = JOINT_RE.match(g.name)
                if m:
                    jog[g.index] = int(m.group(1))  # joints this part lacks are rejected below
                elif g.name in arm.data.bones:
                    jog[g.index] = g.name  # custom bone; id decided once weights are known
            verts, tris, tri_slots = mesh_data(o, jog)
            stray = sorted({j for v in verts for j, w in v["weights"] if w > L.MIN_WEIGHT
                            and isinstance(j, int) and j not in std})
            if stray:
                raise L.ExportError(f"{o.name}: weighted to {', '.join(f'j{j:03d}' for j in stray)}, "
                                    f"which the {col.name} part doesn't have")
            cx = sum(v["pos"][0] for v in verts) / max(1, len(verts))
            group = object_group(o, cx, warnings)
            # one mesh (or several, see split_pieces) per material slot in use
            for slot in sorted(set(tri_slots)):
                mat = slot_material(o, slot, tpl)
                if tpl["mats"][mat]["slots"] == (0, 0, 0):
                    # the untextured (shadow) material: shadow copies are generated below, and
                    # drawn as normal meshes these show black (imported shadow meshes)
                    warnings.append(f"{o.name}: faces on the untextured shadow material {mat} skipped")
                    continue
                sv, st = subset(verts, [t for t, ts in zip(tris, tri_slots) if ts == slot])
                for pv, pt in split_pieces(sv, st):
                    meshes.append(dict(group=group, mat=mat, lodmask=L.LOD_ALL, verts=pv, tris=pt, name=o.name))
    finally:
        arm.data.pose_position = pose_pos
        bpy.context.view_layer.update()

    # custom bones: only those carrying real weight here (plus the links up to the skeleton)
    used_custom = {j for m in meshes for v in m["verts"] for j, w in v["weights"]
                   if isinstance(j, str) and w > L.MIN_WEIGHT}
    customs, custom_ids = custom_bones_for(arm, tpl, used_custom, root.name, warnings)
    for m in meshes:
        for v in m["verts"]:
            v["weights"] = [(custom_ids[j] if isinstance(j, str) else j, w) for j, w in v["weights"]
                            if not isinstance(j, str) or j in custom_ids]

    data, rep = L.build_model(tpl, customs, meshes, shadow=shadow)
    rep["warnings"] = warnings + rep["warnings"]
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{base_name(col.name).lower()}.rModel")
    with open(path, "wb") as f:
        f.write(data)
    rep["path"], rep["template"] = path, tpath
    rep["custom"] = {c["name"]: c["joint"] for c in customs}
    rep["armature"] = arm
    return rep


# ---------------------------------------------------------------- textures

TEX_ROLE_RE = re.compile(r"_(A|B|C|D|NM|MM)$", re.I)


def part_textures(col, setdir, slot, warnings):
    """Custom textures of a part: image textures in its materials named <anything>_A.._D (colour
    maps), _NM (normal map) or _MM (shininess mask), encoded to .rTexture next to the models.
    Game textures loaded by the importer (from the extracted raw/ folder) are the template's own
    and are left out. -> {"BM_A": file, "NM": file, ...}"""
    import numpy as np
    found = {}
    for o in col.all_objects:
        if o.type != "MESH" or o.hide_render:
            continue
        for ms in o.material_slots:
            mat = ms.material
            if mat is None or not mat.use_nodes or mat.node_tree is None:
                continue
            for node in mat.node_tree.nodes:
                img = getattr(node, "image", None) if node.type == "TEX_IMAGE" else None
                if img is None:
                    continue
                path = bpy.path.abspath(img.filepath) if img.filepath else ""
                if path.startswith(RAW) or "-00" in img.name:
                    continue  # the template's own texture
                stem = os.path.splitext(img.name)[0]
                m = TEX_ROLE_RE.search(stem) or TEX_ROLE_RE.search(os.path.splitext(os.path.basename(path))[0])
                if not m:
                    continue
                r = m.group(1).upper()
                role = "BM_" + r if r in "ABCD" else r
                if role in found and found[role] is not img:
                    warnings.append(f"{slot}: more than one {role} image ({found[role].name}, {img.name}); using {found[role].name}")
                    continue
                found[role] = img
    out = {}
    for role, img in sorted(found.items()):
        w, h = img.size
        if not w or not h:
            warnings.append(f"{slot}: {img.name} has no pixels (not found?), skipped")
            continue
        src = img
        if w & (w - 1) or h & (h - 1):
            nw, nh = 1 << (w - 1).bit_length(), 1 << (h - 1).bit_length()
            warnings.append(f"{slot}: {img.name} is {w}x{h}, scaled to {nw}x{nh} (use powers of two)")
            src = img.copy()
            src.scale(nw, nh)
            w, h = nw, nh
        px = np.array(src.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1]  # Blender stores bottom-up
        rgba = np.clip(np.round(px * 255), 0, 255).astype(np.uint8)
        kind = "nm" if role == "NM" else "mm" if role == "MM" else "bm"
        data = lp2tex.encode(rgba, kind, mips=min(5, max(1, min(w, h).bit_length() - 2)))
        name = f"{slot}_{role}.rTexture"
        os.makedirs(setdir, exist_ok=True)
        with open(os.path.join(setdir, name), "wb") as f:
            f.write(data)
        out[role] = name
        if src is not img:
            bpy.data.images.remove(src)
    return out


def export_sets(outdir, names=None):
    sets = find_sets(names)
    if not sets:
        raise L.ExportError("no LPC_<id>_<faction>_<name> collection found")
    parsed = [(root,) + parse_set_name(root) for root in sets]
    seen = {}
    for root, sid, _, _ in parsed:
        if sid.lower() in seen:
            raise L.ExportError(f"id '{sid}' used by both {seen[sid.lower()]} and {root.name}")
        seen[sid.lower()] = root.name
    lines, exported = [], {}
    for root, sid, fac, name in parsed:
        parts = part_collections(root)
        if not parts:
            raise L.ExportError(f"{root.name}: no body/head/back/legs collections inside")
        setdir = os.path.join(outdir, f"LPC_{sid}")
        lines.append(f"== {sid}: \"{name}\" ({FACTION_NAMES[fac]})")
        meta = dict(id=sid, name=name, faction=fac, faction_index=FACTIONS[fac], parts={})
        for prefix, col in parts.items():
            slot = base_name(col.name).lower()
            if not any(o.type == "MESH" and not o.hide_render for o in col.all_objects):
                lines.append(f"  {slot}: empty, skipped")
                continue
            rep = export_part(root, prefix, col, setdir)
            exported.setdefault(rep["armature"].name, set()).update(rep["custom"])
            meta["parts"][slot] = dict(file=os.path.basename(rep["path"]), template=os.path.basename(rep["template"]),
                                       custom_joints=rep["custom"])
            tex = part_textures(col, setdir, slot, rep["warnings"])
            if tex:
                meta["parts"][slot]["textures"] = tex
            lines.append(f"  {slot}: {rep['vertices']} verts, {rep['triangles']} tris, {rep['meshes']} pieces "
                         f"(incl. shadow), {rep['bones']} bones ({rep['custom_bones']} custom), "
                         f"{rep['bytes'] // 1024} KB -> {rep['path']}")
            if rep["custom"]:
                lines.append("    custom joint ids: " + ", ".join(f"{n}={j}" for n, j in rep["custom"].items()))
            if tex:
                lines.append("    textures: " + ", ".join(f"{r}={f}" for r, f in tex.items()))
            for w in rep["warnings"]:
                lines.append("    WARNING: " + w)
        with open(os.path.join(setdir, "lpc.json"), "w") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)
    for arm_name, done in exported.items():
        arm = bpy.data.objects[arm_name]
        idle = [b.name for b in arm.data.bones if not JOINT_RE.match(b.name) and b.name not in done]
        if idle:
            lines.append(f"NOTE: {arm_name}: custom bones with no weights, not exported: {', '.join(idle)}")
    report = "\n".join(lines)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "export_report.txt"), "w") as f:
        f.write(report + "\n")
    return report


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    outdir = argv[0] if argv else bpy.path.abspath("//lp2_export")
    try:
        print(export_sets(outdir, argv[1:] or None))
        print("LP2 export done")
    except L.ExportError as e:
        print("LP2 EXPORT ERROR:", e)
        if bpy.app.background:
            sys.exit(1)
