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
# Meshes are skinned to LP2_rig (vertex groups = game joints by name: r_upperarm, chest... or the old jNNN;
# lp2bones.py lists the names and the aliases read). Bones that are no standard joint are
# custom: each chain must hang off a joint the part already has; only bones carrying weight
# (and the links between them and the skeleton) are exported; ids are assigned once and
# stored on the bone as "lp2_joint". Only the high detail level is authored: every mesh is
# exported for all distances and gets a shadow copy. Effects: the template part's effects (lamps) are
# dropped ("effects": "none" in lpc.json) unless the part / LPC collection has lp2_effects = "template".
# Materials, per material slot: the material's
# (or object's) custom property "lp2_mat" (template material index), else the importer's
# <part>_matNNN name, else the template's first textured material.
# The template (standard skeleton, materials, textures) is the part's original rModel:
# custom property "lp2_template" on the part or LPC collection, else the lp2_source of an
# imported object of that slot, else the 29xx (Femmes Fatales) part.
import bpy, bmesh, json, os, re, struct, sys
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2model as L  # noqa: E402
import lp2tex  # noqa: E402
import rchain  # noqa: E402
import lp2bones as B  # noqa: E402

SLOTS = {"body": "bd", "head": "hd", "back": "bk", "legs": "lg"}
RAW = os.path.expanduser("~/Projects/lp2-assets/raw/CustomParts")
DEFAULT_TEMPLATE = RAW + "/{p}2900/model/hm/hm29/{p}2900/{p}2900.rModel"
HAND_POSES = {"grip": (200, 201), "open": (202, 203), "fist": (None, 204), "peace": (None, 205),
              "point": (None, 206), "thumb": (None, 207)}
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

CORE_JOINT_MAX = 19  # j000-j019: identical in every stock part, so they can move between parts
JOINT_MAX = 127  # highest custom joint id (stock body/leg chains never go above it)


def borrow_joint(root, joint):
    """The bone record of a standard joint from another part template of this set (e.g. the
    legs' thighs for a body whose waist hangs below the pelvis), with its template's bones."""
    for c in root.children_recursive:
        path = c.get("lp2_template")
        if not path or not os.path.exists(bpy.path.abspath(path)):
            continue
        bones = L.read_template(open(bpy.path.abspath(path), "rb").read())["bones"]
        for b in bones:
            if b["joint"] == joint and b["parent"] != 255:
                return dict(bone=b, bones=bones)
    return None


def borrowed_bones(borrowed, std, warnings, part):
    """Borrowed standard joints as build_model custom bones (parents-first via its queue)."""
    out = []
    for j, src in sorted(borrowed.items()):
        b, bones = src["bone"], src["bones"]
        pj = bones[b["parent"]]["joint"]
        if pj not in std and pj not in borrowed:
            raise L.ExportError(f"{part}: {B.name_of(j)} hangs off {B.name_of(pj)}, which neither this part nor the set's other parts give it")
        out.append(dict(name=B.name_of(j), joint=j, parent=pj, local=b["local"], radius=b["radius"],
                        mirror_joint=bones[b["mirror"]]["joint"]))
    if out:
        warnings.append(f"NOTE: {part}: added standard joints {', '.join(c['name'] for c in out)} from the set's other parts")
    return out


def custom_bones_for(arm, tpl, used_names, set_name, warnings):
    """Custom bones (non-jNNN) this part needs: weighted ones, their ancestors and their
    descendants. Assigns and stores lp2_joint ids. -> list for lp2model, {name: joint}."""
    std = {b["joint"] for b in tpl["bones"]}
    bones = arm.data.bones
    custom = [b for b in bones if B.joint_of(b.name) is None]
    if len(custom) > L.MAX_CUSTOM_BONES:
        raise L.ExportError(f"{arm.name}: {len(custom)} custom bones (cap {L.MAX_CUSTOM_BONES})")
    # weighted bones plus the unweighted links between them and the part's skeleton
    need = set()
    # chain bones (bone physics) need their whole line, weighted or not: the tips pull the rest
    used_names = set(used_names) | {d.name for b in custom if b.get("lp2_chain") and (b.name in used_names or any(
        c.name in used_names for c in b.children_recursive)) for d in [b, *b.children_recursive]}
    for name in used_names:
        b = bones[name]
        while b is not None and B.joint_of(b.name) is None:
            need.add(b.name)
            b = b.parent
    # ids: keep stored ones, then hand out free ones from JOINT_MAX down
    # our chains on ids 237-254 never moved, so stored ids above JOINT_MAX are handed out again
    for b in custom:
        if "lp2_joint" in b and int(b["lp2_joint"]) > JOINT_MAX:
            del b["lp2_joint"]
    taken = {b["joint"] for b in tpl["bones"]} | {int(b["lp2_joint"]) for b in custom if "lp2_joint" in b}
    out, ids = [], {}
    for b in sorted((bones[n] for n in need), key=lambda b: (len(b.parent_recursive), b.name)):  # same ids every run
        if "lp2_joint" not in b:
            free = next((i for i in range(JOINT_MAX, CORE_JOINT_MAX, -1) if i not in taken), None)
            if free is None:
                raise L.ExportError("no free joint ids left")
            b["lp2_joint"] = free
            taken.add(free)
        j = int(b["lp2_joint"])
        p = b.parent
        if p is None:
            raise L.ExportError(f"custom bone {b.name} has no parent; parent it to a standard joint of this part")
        if B.joint_of(p.name) is not None:
            pj = B.joint_of(p.name)
            if pj not in std:
                raise L.ExportError(f"custom bone {b.name} hangs off {p.name}, which this part does not have "
                                    f"(it has {', '.join(B.name_of(x) for x in sorted(std))})")
        else:
            pj = int(p["lp2_joint"])
        ids[b.name] = j
        out.append(dict(name=b.name, joint=j, parent=pj,
                        world=to_lp2(arm.matrix_world @ b.head_local)))
    return out, ids


# ---------------------------------------------------------------- export

def roughness_to_power(r):
    """Principled roughness -> Blinn-Phong specular power (inverse of the importer's)."""
    r = min(max(r, 0.02), 1.0)
    return 2.0 / r ** 4 - 2.0


def material_settings(bm):
    """(spec_power or None, spec_colour or None) a Blender material asks for: Roughness (when not
    driven by a texture) -> spec_power, the "lp2_spec_colour" property -> spec_colour."""
    power = colour = None
    if bm.use_nodes and bm.node_tree is not None:
        bsdf = next((n for n in bm.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None and not bsdf.inputs["Roughness"].is_linked:
            power = roughness_to_power(bsdf.inputs["Roughness"].default_value)
    if "lp2_spec_colour" in bm:
        colour = float(bm["lp2_spec_colour"])
    return power, colour


def apply_material_settings(tpl, mat_src, warnings):
    """Writes changed spec_power (word 18) / spec_colour (words 20-22) of each lit template
    material into tpl["mat_block"] (all colours), and returns per-colour overrides from the
    materials' "lp2_spec_power_<letter>" / "lp2_spec_colour_<letter>" properties
    ({letter: {material index: {"spec_power": p, "spec_colour": c}}} for lpc.json)."""
    block = bytearray(tpl["mat_block"])
    overrides = {}
    for idx, bms in sorted(mat_src.items()):
        o = idx * 160
        if block[o] != 0x43:
            continue  # not a lit material
        stock_power = struct.unpack_from("<f", block, o + 18 * 4)[0]
        stock_colour = struct.unpack_from("<f", block, o + 20 * 4)[0]
        firsts = {}
        for bm in bms:
            for key, val in zip(("spec_power", "spec_colour"), material_settings(bm)):
                if val is None:
                    continue
                if key in firsts and abs(firsts[key][1] - val) > 1e-3 and firsts[key][0] is not bm:
                    warnings.append(f"material {idx}: {firsts[key][0].name} and {bm.name} ask for different {key}; using {firsts[key][0].name}")
                    continue
                firsts.setdefault(key, (bm, val))
            for letter in "ABCD":
                for key in ("spec_power", "spec_colour"):
                    prop = f"lp2_{key}_{letter}"
                    if prop in bm:
                        overrides.setdefault(letter, {}).setdefault(str(idx), {})[key] = round(float(bm[prop]), 3)
        if "spec_power" in firsts:
            p = firsts["spec_power"][1]
            if abs(p - stock_power) > max(0.5, stock_power * 0.03):  # roughness round trip noise
                struct.pack_into("<f", block, o + 18 * 4, p)
        if "spec_colour" in firsts:
            c = firsts["spec_colour"][1]
            if abs(c - stock_colour) > 1e-3:
                for w in (20, 21, 22):
                    struct.pack_into("<f", block, o + w * 4, c)
    tpl["mat_block"] = bytes(block)
    return overrides


def export_part(root, prefix, col, outdir, shadow=True):
    warnings = []
    tpath, w = template_path(root, col, prefix)
    if w:
        warnings.append(w)
    if not os.path.exists(tpath):
        raise L.ExportError(f"template not found: {tpath}")
    tpl = L.read_template(open(tpath, "rb").read())
    std = {b["joint"] for b in tpl["bones"]}
    borrowed = {}  # standard joint -> its bone record from a sibling part's template
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
    mat_src = {}  # template material index -> the Blender materials exported with it
    try:
        meshes = []
        for o in sorted(objs, key=lambda o: o.name):
            jog = {}
            for g in o.vertex_groups:
                j = B.joint_of(g.name)
                if j is not None:
                    jog[g.index] = j  # joints this part lacks are rejected below
                elif g.name in arm.data.bones:
                    jog[g.index] = g.name  # custom bone; id decided once weights are known
            verts, tris, tri_slots = mesh_data(o, jog)
            stray = sorted({j for v in verts for j, w in v["weights"] if w > L.MIN_WEIGHT
                            and isinstance(j, int) and j not in std})
            for j in [j for j in stray if j <= CORE_JOINT_MAX and j not in borrowed]:
                src = borrow_joint(root, j)  # e.g. thighs for a body that covers the hips (as bd2100)
                if src:
                    borrowed[j] = src
            stray = [j for j in stray if j not in borrowed]
            if stray:
                raise L.ExportError(f"{o.name}: weighted to {', '.join(B.name_of(j) for j in stray)}, "
                                    f"which the {col.name} part doesn't have")
            cx = sum(v["pos"][0] for v in verts) / max(1, len(verts))
            group = object_group(o, cx, warnings)
            # one mesh (or several, see split_pieces) per material slot in use
            for slot in sorted(set(tri_slots)):
                mat = slot_material(o, slot, tpl)
                if slot < len(o.material_slots) and o.material_slots[slot].material is not None:
                    mat_src.setdefault(mat, []).append(o.material_slots[slot].material)
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
    customs = borrowed_bones(borrowed, std, warnings, col.name) + customs
    for m in meshes:
        for v in m["verts"]:
            v["weights"] = [(custom_ids[j] if isinstance(j, str) else j, w) for j, w in v["weights"]
                            if not isinstance(j, str) or j in custom_ids]

    overrides = apply_material_settings(tpl, mat_src, warnings)
    data, rep = L.build_model(tpl, customs, meshes, shadow=shadow)
    rep["overrides"] = overrides
    rep["warnings"] = warnings + rep["warnings"]
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{base_name(col.name).lower()}.rModel")
    with open(path, "wb") as f:
        f.write(data)
    rep["path"], rep["template"] = path, tpath
    rep["custom"] = {c["name"]: c["joint"] for c in customs}
    rep["armature"] = arm
    rep["chain"] = None
    chains = bone_chains(arm, custom_ids)
    if chains:  # bone physics: custom bones marked "lp2_chain" and the single-child line below each
        cpath = os.path.splitext(path)[0] + ".rChain"
        with open(cpath, "wb") as f:
            f.write(rchain.build(chains))
        rep["chain"] = os.path.basename(cpath)
        rep["chains"] = chains
    return rep


def bone_chains(arm, custom_ids):
    """[[joint id, ...], ...] for each exported custom bone with the "lp2_chain" property: that bone
    and the line of exported custom bones below it (one child each)."""
    out = []
    for name, j in custom_ids.items():
        b = arm.data.bones[name]
        if not b.get("lp2_chain"):
            continue
        chain = [j]
        while True:
            kids = [c for c in b.children if c.name in custom_ids]
            if len(kids) != 1:
                break
            b = kids[0]
            chain.append(custom_ids[b.name])
        if len(chain) < 2:
            raise L.ExportError(f"chain bone {name}: needs at least one exported custom bone below it")
        out.append(chain)
    return out


# ---------------------------------------------------------------- textures

TEX_ROLE_RE = re.compile(r"_((?:NM|MM)_[A-D]|A|B|C|D|NM|MM)$", re.I)


def part_textures(col, setdir, slot, warnings):
    """Custom textures of a part: image textures in its materials named <anything>_A.._D (colour
    maps), _NM (normal map) or _MM (shininess mask), or _MM_B / _NM_C (that colour's own mask /
    normal map, the shared one elsewhere), encoded to .rTexture next to the models.
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
        kind = "nm" if role.startswith("NM") else "mm" if role.startswith("MM") else "bm"
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
            # the template's effects (the 29xx parts' lamps) sit where its own model had them: off unless
            # the part (or set) collection says lp2_effects = "template"
            if str(col.get("lp2_effects", root.get("lp2_effects", "none"))).lower() != "template":
                meta["parts"][slot]["effects"] = "none"
            if rep["chain"]:
                meta["parts"][slot]["chain"] = rep["chain"]
                lines.append(f"    chains: {len(rep['chains'])} -> {rep['chain']} (" + "; ".join(",".join(map(str, c)) for c in rep["chains"]) + ")")
            if rep["overrides"]:
                meta["parts"][slot]["material_overrides"] = rep["overrides"]
                lines.append("    colour overrides: " + json.dumps(rep["overrides"]))
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
        # menu colours: the root collection's "lpc_colours" property ("ACD"), else A plus every
        # letter some part has its own colour / mask / normal map or material overrides for
        letters = str(root.get("lpc_colours", "")).upper()
        if not letters:
            own = {r[3] for p in meta["parts"].values() for r in p.get("textures", {}) if r[:3] in ("BM_", "MM_", "NM_") and len(r) == 4}
            own |= {c for p in meta["parts"].values() for c in p.get("material_overrides", {})}
            letters = "".join(sorted(own | {"A"}))
        meta["colours"] = "".join(c for i, c in enumerate(letters) if c in "ABCD" and c not in letters[:i]) or "A"
        lines.append(f"  colours: {meta['colours']}")
        with open(os.path.join(setdir, "lpc.json"), "w") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)
    for arm_name, done in exported.items():
        arm = bpy.data.objects[arm_name]
        idle = [b.name for b in arm.data.bones if B.joint_of(b.name) is None and b.name not in done]
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
