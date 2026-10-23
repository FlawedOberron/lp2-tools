# Blender headless: port a Lost Planet 1 character (lp1model.py) onto the LP2 skeleton as an LPC_ set
# ready for lp2_blender_export.py.
#   flatpak run --filesystem=... org.blender.Blender -b --python lp1port.py -- OUT.blend LP1_MODEL ID FACTION "Display name" [TEMPLATE_SERIES]
#       [--head HEAD_MODEL] [--body-groups G,G...]
#   e.g.  ... -- ~/Projects/lp2-assets/lp1/port/snowbunny.blend .../hm70/hm70.0x1041bd9e lp1sb FF "Snow Bunny" 2900
#   --head: a separate head model (cutscene heads, e.g. hmcc for Basil): its root sits on the body's
#     neck (j009), its face bones fold into the head (j010); all of it goes to the head part.
#   --body-groups: LP1 mesh groups that go to the body whatever their joints (a poncho, a pouch).
#   --chains: LP1 joints that start bone strands to keep (with everything below them) as custom
#     bones lp1_<joint>, weights intact; each start is tagged lp2_chain, so the exporter writes the
#     part's rChain (bone physics, rchain.py; Basil's poncho: 56,60,64,68,70,72).
#   --energy-hue DEG: recolour the energy lines in the colour maps (saturated purple-magenta texels,
#     hue 260-340) to this hue, keeping their brightness and shading (Valkyrie: 28 = LP2 orange).
#     A stopgap: the plan is a player energy colour applied to every custom part (see notes).
#   --drop-groups G,G: leave these LP1 mesh groups out (Basil without her poncho / pouch: 6,17).
#   --trim-legs 1: leg triangles above the template body's floor go to the body only (default: both, so the legs
#       still fill the gap under other torsos; Basil's poked above her belt).
#   --parts P,P: only make these parts (head, body, legs), e.g. an alternative torso as its own set.
#   --skirt G,G[:N]: bone physics for a skirt with no bones of its own (Snow Bunny: 5,10): N strands
#     (default 8) of 3 bones are placed around those mesh groups from the waistband to the hem, off
#     the pelvis like the FF legs' flaps (lg2901); each skirt vertex blends its two nearest strands by
#     angle and slides down them by height, keeping part of its leg weights (so the legs still push
#     the skirt; there is no collision). The strands' roots are chain starts.
# Joints past the core skeleton (LP1 j000-j018: fingers, cloth, hair) fold into their nearest core
# ancestor; the parts are rigid there.
# LP1 and LP2 share the skeleton up to numbering (LP2 inserts the pelvis j001: LP1 j001-j020 = LP2
# j002-j021, LP1 root -> LP2 pelvis) and proportions (LP1 legs ~4 cm longer, arms ~5 cm shorter):
# every vertex is moved by its weighted joint offsets (both rigs are T-posed, unrotated).
# Triangles go to head / legs / body by their main joint; each part's LP1 texture sets are packed
# into one atlas per role (_A.._D colour maps from LP1's own A-D variants, _NM, _MM) with the UVs
# remapped, since an LP2 part wears one texture set.
# Hands: LP1 bakes one open hand into the arm; LP2 swaps hand meshes per pose (groups 200-207). The
# LP1 hand (past the wrist) is cut off and the body template's hand meshes are copied in, their
# texture placed in a spare atlas cell and tinted, per colour letter, to the LP1 glove's average.
# Waist: stock bodies reach below the pelvis and stock legs stop above it, so any body covers any
# legs. Leg triangles above the template body's lowest point are copied into the body as well.
import bpy, math, os, re, struct, sys
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp1model, lp1tex, mod2obj as M2  # noqa: E402
import lp2_blender_import as IMP  # noqa: E402

RAW = os.path.expanduser("~/Projects/lp2-assets/raw/CustomParts")
LP1_TO_LP2 = {0: 1, **{j: j + 1 for j in range(1, 19)}}  # core joints; the rest fold into these
LP1_NECK, LP1_HEAD = 9, 10
PART_OF = {10: "head", 11: "head", **{j: "legs" for j in range(1, 8)}}  # else body
PREFIX = {"head": "hd", "body": "bd", "legs": "lg"}
ATLAS_MAX = 1024
CUTOUT = 0.25  # share of see-through texels that makes an LP1 colour map a cut-out (Basil hm05-04: 73%)
HAND_GROUPS = range(200, 208)
WRIST = {15: -1, 19: 1}  # LP2 wrist joints, by side (x sign)
THIGHS = {2, 5}  # LP2 hip joints: the body's waist copies keep their leg weights
WAIST_PUSH = 0.2  # cm the body's waist copies sit outside our own legs (no z-fighting)


def template(part, series):
    p = PREFIX[part]
    return f"{RAW}/{p}{series}/model/hm/hm{series[:2]}/{p}{series}/{p}{series}.rModel"


def world_joints(bones, local_key="local"):
    W, out, parent = {}, {}, {}
    for i, bn in enumerate(bones):
        m = np.array(bn[local_key]).reshape(4, 4)
        W[i] = m if bn["parent"] == 255 else m @ W[bn["parent"]]
        out[bn["joint"]] = W[i][3, :3]
        parent[bn["joint"]] = bones[bn["parent"]]["joint"] if bn["parent"] != 255 else None
    return out, parent


def template_info(path):
    b = open(path, "rb").read()
    bones, _ = M2.read_bones(b)
    Md = M2.read_model(b)
    # the plain material: the textured one covering the most vertices
    use = {}
    for m in Md["meshes"]:
        if m["mat"] < len(Md["mats"]) and tuple(Md["mats"][m["mat"]]) != (0, 0, 0):
            use[m["mat"]] = use.get(m["mat"], 0) + m["vc"]
    plain = max(use, key=use.get)
    # its alpha-tested twin: same flags plus 0x4000 (the stock parts' cut-out materials)
    tex_off, ntex = struct.unpack_from("<I", b, 0x2C)[0], struct.unpack_from("<I", b, 0x1C)[0]
    flags = [struct.unpack_from("<I", b, tex_off + 64 * ntex + 160 * i)[0] for i in range(len(Md["mats"]))]
    cut = next((i for i, f in enumerate(flags) if f == flags[plain] | 0x4000 and f != flags[plain]), None)
    return bones, plain, cut


def load_rgba(tex_path, cache):
    """LP1 texture -> float RGBA (H, W, 4), bottom-up rows like Blender."""
    dds = os.path.join(cache, os.path.basename(tex_path) + ".dds")
    open(dds, "wb").write(lp1tex.to_dds(lp1tex.read_tex(open(tex_path, "rb").read())))
    img = bpy.data.images.load(dds)
    img.alpha_mode = "CHANNEL_PACKED"
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return px


def rgb_normals(px):
    """PC LP1 normal maps are DXT5nm (X in alpha, Y in green, red and blue pinned at 1); the 360's
    (CTX1, decoded by lp1tex) are already RGB. -> ordinary RGB normal map."""
    if px[..., 0].min() < 0.98 or px[..., 2].min() < 0.98:
        return px
    x, y = px[..., 3] * 2 - 1, px[..., 1] * 2 - 1
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
    return np.dstack([px[..., 3], px[..., 1], z * 0.5 + 0.5, np.ones_like(z)]).astype(np.float32)


def energy_hue(px, hue):
    """Purple-magenta texels (LP1 energy lines) -> hue (degrees), same saturation and value; the
    key fades in over saturation 0.25-0.4 so compressed edges blend."""
    rgb = px[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    h = np.degrees(np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)) % 360
    w = np.clip((sat - 0.25) / 0.15, 0, 1) * ((h >= 260) & (h <= 340)) * (mx > 0.15)
    if not w.any():
        return px
    # rebuild from value, saturation and the new hue (HSV -> RGB)
    k = lambda n: (n + hue / 60.0) % 6
    f = lambda n: mx - mx * sat * np.clip(np.minimum(k(n), 4 - k(n)), 0, 1)
    new = np.dstack([f(5), f(3), f(1)])
    out = px.copy()
    out[..., :3] = rgb * (1 - w[..., None]) + new * w[..., None]
    print(f"energy lines: {int((w > 0.5).sum())} texels -> hue {hue:g}")
    return out


def resize(px, s):
    h, w = px.shape[:2]
    if (w, h) == (s, s):
        return px
    ys = (np.arange(s) * h // s)
    xs = (np.arange(s) * w // s)
    return px[ys][:, xs]


def template_hands(body_tpl):
    """The imported body template's hi-LOD hand meshes and its texture files."""
    stem = os.path.splitext(os.path.basename(body_tpl))[0]
    objs = [o for o in bpy.data.objects if o.type == "MESH" and o.get("lp2_source") == body_tpl
            and int(o.get("lp2_group", 0)) in HAND_GROUPS and int(o.get("lp2_lodmask", 0)) & 1]
    d = os.path.dirname(body_tpl)
    tex = {"_NM": os.path.join(d, f"{stem}_NM-00.dds"), "_MM": os.path.join(d, f"{stem}_MM-00.dds")}
    for k, L in enumerate("ABCD"):  # colour variants live in the bd290000..03 extractions
        tex[f"_{L}"] = d.replace(f"{os.sep}{stem}{os.sep}model", f"{os.sep}{stem}{k:02d}{os.sep}model") + f"{os.sep}{stem}_BM-00_{L}.dds"
    uvs = [tuple(l.uv) for o in objs for l in o.data.uv_layers.active.data]
    return dict(objects=objs, tex=tex, uvs=uvs)


def dds_rgba(path):
    img = bpy.data.images.load(path)
    img.alpha_mode = "CHANNEL_PACKED"
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return px


def sample(px, uvs):
    h, w = px.shape[:2]
    return np.array([px[min(h - 1, int(v * h)), min(w - 1, int(u * w))] for u, v in uvs])


def hand_texture(hands, suffix, hand_tris, lp1_px):
    """The template's hand texture for one atlas role; colour maps tinted to the LP1 glove."""
    letter = suffix[1:] if suffix[1:] in "ABCD" else None
    src = hands["tex"].get(suffix) or hands["tex"]["_A"]
    if letter and not os.path.exists(src):
        src = hands["tex"]["_A"]
    px = dds_rgba(src)
    if suffix == "_NM":  # the game's layout (X in alpha, Y in green) -> ordinary RGB normal map
        x, y = px[..., 3] * 2 - 1, px[..., 1] * 2 - 1
        z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
        return np.dstack([px[..., 3], px[..., 1], z * 0.5 + 0.5, np.ones_like(z)])
    if not letter:
        return px
    lp1 = [c for s, uv3 in hand_tris if s in lp1_px for c in sample(lp1_px[s], uv3)]
    if not lp1:
        return px
    target = np.mean(lp1, 0)[:3]
    lum = px[..., :3] @ np.array([0.299, 0.587, 0.114])
    ref = sample(px, hands["uvs"])[:, :3] @ np.array([0.299, 0.587, 0.114])
    scale = lum / max(1e-3, float(np.mean(ref)))
    out = px.copy()
    out[..., :3] = np.clip(scale[..., None] * target, 0, 1)
    return out


def load_source(path):
    b = open(path, "rb").read()
    bones = lp1model.read_bones(b)
    pos, par = world_joints(bones)

    def core(j):
        while j not in LP1_TO_LP2 and par.get(j) is not None:
            j = par[j]
        return j if j in LP1_TO_LP2 else 0

    return dict(path=path, b=b, M=lp1model.read_model(b), pos=pos, par=par, core={j: core(j) for j in pos},
                jmap={j: core(j) for j in pos}, shift=np.zeros(3), part=None)


def make_skirt(src, groups, n):
    """Skirt strands around the given mesh groups (LP1 space, front = +z): per strand 3 bones
    (waistband, middle, hem) from that sector's vertices, and a weight function for the vertices."""
    b, M = src["b"], src["M"]
    pts = np.array([lp1model.vertex(b, M, m, i)[0] for m in M["meshes"] if m["group"] in groups and m["lodmask"] & 1
                    and M["mats"][m["mat"]][0] for t in lp1model.mesh_geometry(b, M, m) for i in t])
    ang = np.degrees(np.arctan2(pts[:, 0], pts[:, 2])) % 360
    rad = np.hypot(pts[:, 0], pts[:, 2])
    y_top, y_hem = np.percentile(pts[:, 1], 97), np.percentile(pts[:, 1], 1)
    bones, starts, step = [], [], 360.0 / n
    for k in range(n):
        a = k * step
        near = np.abs((ang - a + 180) % 360 - 180) < step / 2
        top, hem = pts[:, 1] > y_top - 0.15 * (y_top - y_hem), pts[:, 1] < y_hem + 0.15 * (y_top - y_hem)
        r_top = np.median(rad[near & top] if (near & top).any() else rad[top])  # a sector with a gap: the band's
        r_hem = np.median(rad[near & hem] if (near & hem).any() else rad[hem])
        th = np.radians(a)
        for i, t in enumerate((0.0, 0.5, 1.0)):
            r, y = r_top + t * (r_hem - r_top), y_top + t * (y_hem - y_top)
            name = f"skirt{k}_{i}"
            bones.append((name, np.array((r * np.sin(th), y, r * np.cos(th))), 0, f"skirt{k}_{i - 1}" if i else None))
        starts.append(f"skirt{k}_0")

    def weights(pos, sk):
        t = min(1.0, max(0.0, (y_top - pos[1]) / (y_top - y_hem)))
        share = 0.6 * min(1.0, max(0.0, (t - 0.15) / 0.6))  # the waistband stays on the pelvis
        if share <= 0:
            return sk
        u = (np.degrees(np.arctan2(pos[0], pos[2])) % 360) / step
        k0, a = int(u) % n, u - int(u)
        lower = min(1.0, max(0.0, (t - 0.35) / 0.3))  # the upper half rides bone 0, the lower bone 1
        out = [(j, w * (1 - share)) for j, w in sk]
        for k, wk in ((k0, 1 - a), ((k0 + 1) % n, a)):
            out += [(f"skirt{k}_0", share * wk * (1 - lower)), (f"skirt{k}_1", share * wk * lower)]
        return [(j, w) for j, w in out if w > 1e-3]

    print(f"skirt: {n} strands, y {y_top:.1f} to {y_hem:.1f}, {len(pts)} vertex refs")
    return dict(bones=bones, starts=starts, groups=groups, weights=weights)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    opts = {}
    while len(argv) > 1 and argv[-2].startswith("--"):
        opts[argv[-2]] = argv[-1]
        argv = argv[:-2]
    out_blend, model_path, set_id, faction, display = argv[:5]
    series = argv[5] if len(argv) > 5 else "2900"
    body_groups = {int(g) for g in opts.get("--body-groups", "").split(",") if g}
    drop_groups = {int(g) for g in opts.get("--drop-groups", "").split(",") if g}
    only_parts = set(opts["--parts"].split(",")) if "--parts" in opts else set(PREFIX)
    cache = os.path.join(os.path.dirname(os.path.abspath(out_blend)), set_id + "_tex")
    os.makedirs(cache, exist_ok=True)

    srcs = [load_source(model_path)]
    p1, par1, core1 = srcs[0]["pos"], srcs[0]["par"], srcs[0]["core"]
    chain_roots = [int(j) for j in opts.get("--chains", "").split(",") if j]
    kept = []  # LP1 joints kept as custom bones, parents first
    for r in chain_roots:
        if r not in p1 or r in LP1_TO_LP2:
            raise SystemExit(f"--chains: j{r} is not an extra joint of {model_path}")
        todo = [r]
        while todo:
            j = todo.pop(0)
            kept.append(j)
            todo += sorted(k for k, pj in par1.items() if pj == j)
    for j in kept:
        srcs[0]["jmap"][j] = j
    # custom bones: (name, LP1-space head, core joint, parent bone name or None = the core's LP2 joint)
    extra = [(f"lp1_{j}", p1[j], core1[j], f"lp1_{par1[j]}" if par1[j] in kept else None) for j in kept]
    chain_starts = [f"lp1_{r}" for r in chain_roots]
    skirt = None
    if "--skirt" in opts:
        groups, _, n = opts["--skirt"].partition(":")
        skirt = make_skirt(srcs[0], {int(g) for g in groups.split(",")}, int(n or 8))
        extra += skirt["bones"]
        chain_starts += skirt["starts"]
    extra_core = {name: c for name, _, c, _ in extra}
    if "--head" in opts:
        h = load_source(opts["--head"])
        root = next(j for j, pj in world_joints(lp1model.read_bones(h["b"]))[1].items() if pj is None)
        h["jmap"] = {j: LP1_NECK if j == root else LP1_HEAD for j in h["pos"]}
        h["shift"] = p1[LP1_NECK] - h["pos"][root]
        h["part"] = "head"
        srcs.append(h)

    tpl = {part: template(part, series) for part in PREFIX}
    p2, par2, allowed, tmat, tcut = {}, {}, {}, {}, {}
    for part, path in tpl.items():
        bones, tmat[part], tcut[part] = template_info(path)
        w, par = world_joints(bones)
        p2.update(w)
        par2.update(par)
        allowed[part] = {bn["joint"] for bn in bones}

    allowed["waist"] = allowed["body"] | THIGHS

    def to_allowed(j, part):
        while j is not None and j not in allowed[part]:
            j = par2.get(j)
        return j if j is not None else 0

    # ---- reference rig + template parts (hidden from export)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    IMP.import_models([tpl["head"], tpl["body"], tpl["legs"]])
    arm = bpy.data.objects["LP2_rig"]
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = True
    for c in bpy.data.collections:
        if c.name.startswith("LOD"):
            c.hide_render = True

    # the template body's lowest point (Blender z): the body covers down to here
    body_floor = min((o.matrix_world @ v.co).z for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(PREFIX["body"] + series)
                     and any(c.name.endswith("Hi") for c in o.users_collection) for v in o.data.vertices)

    def delta(j):  # an LP1 joint's retarget offset: its core joint's (kept strands ride along)
        c = extra_core[j] if isinstance(j, str) else core1.get(j, j)
        return p2[LP1_TO_LP2[c]] - p1[c]

    def moved(pos, sk):  # sk: [(LP1 joint, w)], pos already in the body model's space
        d = np.zeros(3)
        for j, w in sk:
            d += w * delta(j)
        return np.array(pos) + d

    # custom bones in the rig (kept LP1 strands, generated skirt strands), parents first
    if extra:
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        eb = arm.data.edit_bones
        head = {name: IMP.AXIS @ Vector(tuple(np.array(pos) + delta(name))) * IMP.SCALE for name, pos, _c, _p in extra}
        for name, pos, c, parent in extra:
            b = eb.new(name)
            b.head = head[name]
            kids = [n for n, _pos, _c, pn in extra if pn == name]
            tip = head[kids[0]] if kids else None
            b.tail = tip if tip is not None and (tip - b.head).length > 1e-4 else b.head + Vector((0, 0, -0.03))
            b.parent = eb[parent] if parent else eb[IMP.joint_name(LP1_TO_LP2[c])]
        bpy.ops.object.mode_set(mode="OBJECT")
        for name in chain_starts:
            arm.data.bones[name]["lp2_chain"] = 1

    # ---- vertices
    parts = {p: dict(verts={}, tris=[]) for p in PREFIX}
    hand_tris = []  # (texture set, [uv x3]) of the LP1 hands that are cut off
    jobs = [(si, src, m) for si, src in enumerate(srcs) for m in src["M"]["meshes"]
            if src["M"]["mats"][m["mat"]][0] and m["lodmask"] & 1 and not (si == 0 and m["group"] in drop_groups)]
    for si, src, m in jobs:
        b, M = src["b"], src["M"]
        diffuse = (si, M["mats"][m["mat"]][0])  # (source, 1-based texture slot) = this mesh's texture set
        for t in lp1model.mesh_geometry(b, M, m):
            vs = []
            for i in t:  # into the body model's space, bones folded onto the core LP1 joints
                pos, nrm, uv, sk = lp1model.vertex(b, M, m, i)
                sk = [(src["jmap"][j], w) for j, w in sk]
                if skirt and si == 0 and m["group"] in skirt["groups"]:
                    sk = skirt["weights"](pos, sk)
                vs.append((tuple(np.array(pos) + src["shift"]), nrm, uv, sk))
            score = {}
            for v in vs:
                for j, w in v[3]:
                    j2 = LP1_TO_LP2[extra_core[j] if isinstance(j, str) else core1.get(j, j)]
                    score[j2] = score.get(j2, 0) + w
            main = max(score, key=score.get)
            part = src["part"] or ("body" if m["group"] in body_groups else PART_OF.get(main, "body"))
            if main in WRIST:
                cx = sum(moved(v[0], v[3])[0] for v in vs) / 3
                if cx * WRIST[main] > abs(p2[main][0]) - 1.0:  # past the wrist: the LP1 hand
                    hand_tris.append((diffuse, [v[2] for v in vs]))
                    continue
            targets = [(part, part)]
            if part == "legs" and sum((IMP.AXIS @ Vector(tuple(moved(v[0], v[3])))).z * IMP.SCALE for v in vs) / 3 > body_floor:
                targets = [("body", "waist")] if "--trim-legs" in opts else targets + [("body", "waist")]
            for part, rule in targets:
                P = parts[part]
                ids = []
                for i, (pos, nrm, uv, sk) in zip(t, vs):
                    key = (si, m["voff"], i, diffuse)
                    if key not in P["verts"]:
                        ws = {}
                        for j, w in sk:
                            if isinstance(j, str):  # a generated bone; the body's waist copy stays on its core
                                ja = j if rule != "waist" else to_allowed(LP1_TO_LP2[extra_core[j]], rule)
                            else:
                                ja = f"lp1_{j}" if j not in LP1_TO_LP2 else to_allowed(LP1_TO_LP2[j], rule)
                            ws[ja] = ws.get(ja, 0) + w
                        co = moved(pos, sk) + (WAIST_PUSH * np.array(nrm) / max(1e-6, float(np.linalg.norm(nrm))) if rule == "waist" else 0)
                        P["verts"][key] = (len(P["verts"]), co, nrm, uv, ws, diffuse)
                    ids.append(P["verts"][key][0])
                P["tris"].append(ids)

    root = bpy.data.collections.new(f"LPC_{set_id}_{faction}_{display}")
    bpy.context.scene.collection.children.link(root)
    for part, P in parts.items():
        if not P["tris"] or part not in only_parts:
            continue
        col = bpy.data.collections.new(part)
        root.children.link(col)
        col["lp2_template"] = tpl[part]
        verts = sorted(P["verts"].values(), key=lambda v: v[0])

        # ---- texture atlas for this part's LP1 texture sets
        sets = sorted({v[5] for v in verts})
        cells = sets + (["hand"] if part == "body" and hand_tris else [])
        cols = 1 << math.ceil(math.log2(math.ceil(math.sqrt(len(cells))))) if len(cells) > 1 else 1
        rows = 1 << math.ceil(math.log2(math.ceil(len(cells) / cols))) if len(cells) > cols else 1
        cell = min(512, ATLAS_MAX // max(cols, rows))
        place = {s: (k % cols, rows - 1 - k // cols) for k, s in enumerate(cells)}  # (col, row from bottom)
        hands = template_hands(tpl["body"]) if "hand" in place else None

        def tex_name(s, slot):
            return lp1model.find_tex(srcs[s[0]]["path"], srcs[s[0]]["M"]["texs"][slot - 1]) if slot else None

        def tex_file(s, letter=None):
            src = srcs[s[0]]
            name = src["M"]["texs"][s[1] - 1]
            if letter:
                name = re.sub(r"_[A-D]$", "", name) + "_" + letter
            return lp1model.find_tex(src["path"], name)

        letters = [L for L in "ABCD" if any(tex_file(s, L) for s in sets)] or ["A"]
        roles = {f"_{L}": [(s, tex_file(s, L) or tex_file(s, "A") or tex_file(s)) for s in sets] for L in letters}
        mat_slots = {s: next(mm for mm in srcs[s[0]]["M"]["mats"] if mm[0] == s[1]) for s in sets}
        roles["_NM"] = [(s, tex_name(s, mat_slots[s][1])) for s in sets]
        roles["_MM"] = [(s, tex_name(s, mat_slots[s][2])) for s in sets]
        images, cutout = {}, set()  # cutout: sets whose colour map is mostly holes (laces): keep alpha
        for suffix, files in roles.items():
            atlas = np.zeros((rows * cell, cols * cell, 4), dtype=np.float32)
            atlas[...] = (0.5, 0.5, 1.0, 1.0) if suffix == "_NM" else (0, 0, 0, 1)
            lp1_px = {}
            for s, f in files:
                if not f:
                    continue
                c, r = place[s]
                lp1_px[s] = load_rgba(f, cache)
                if "--energy-hue" in opts and suffix[1:] in "ABCD":
                    lp1_px[s] = energy_hue(lp1_px[s], float(opts["--energy-hue"]))
                if suffix == "_NM":
                    lp1_px[s] = rgb_normals(lp1_px[s])
                atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = resize(lp1_px[s], cell)
                if suffix == "_A" and tcut[part] is not None and (lp1_px[s][..., 3] < 0.5).mean() > CUTOUT:
                    cutout.add(s)
            if hands:
                c, r = place["hand"]
                atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = resize(hand_texture(hands, suffix, hand_tris, lp1_px), cell)
            if suffix not in ("_NM",):
                keep = atlas[..., 3].copy()
                atlas[..., 3] = 1.0  # LP1 keeps masks in alpha; LP2 would read it as transparency
                if suffix[1:] in "ABCD":
                    for s in cutout:
                        c, r = place[s]
                        atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell, 3] = keep[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell]
            name = f"{set_id}_{part}{suffix}"
            img = bpy.data.images.new(name, cols * cell, rows * cell, alpha=True)
            img.pixels[:] = atlas.ravel()
            img.alpha_mode = "CHANNEL_PACKED"
            img.filepath_raw = os.path.join(cache, name + ".png")
            img.file_format = "PNG"
            img.save()
            # as a file image: a generated one is regenerated (flat) when the blend reloads or its
            # colour space changes, which the masks / normal maps then exported
            img.source = "FILE"
            img.filepath = img.filepath_raw
            if suffix in ("_NM", "_MM"):
                img.colorspace_settings.name = "Non-Color"
            img.reload()
            img.pack()
            images[suffix] = img

        mat = bpy.data.materials.new(f"{set_id}_{part}_mat{tmat[part]:03d}")
        mat["lp2_mat"] = tmat[part]
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        for k, (suffix, img) in enumerate(images.items()):
            node = nt.nodes.new("ShaderNodeTexImage")
            node.image = img
            node.location = (-400, 300 - 280 * k)
            if suffix == "_A":
                nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
                nt.links.new(node.outputs["Alpha"], bsdf.inputs["Alpha"])
            elif suffix in ("_NM", "_MM"):
                node.image.colorspace_settings.name = "Non-Color"

        # ---- mesh
        me = bpy.data.meshes.new(f"{set_id}_{part}")
        co = [(IMP.AXIS @ Vector(tuple(v[1]))) * IMP.SCALE for v in verts]
        me.from_pydata(co, [], P["tris"])
        me.shade_smooth()
        me.normals_split_custom_set_from_vertices([(IMP.AXIS.to_3x3() @ Vector(v[2])).normalized() for v in verts])
        uvl = me.uv_layers.new(name="UVMap")
        for poly in me.polygons:
            for li in poly.loop_indices:
                v = verts[me.loops[li].vertex_index]
                c, r = place[v[5]]
                uvl.data[li].uv = ((c + v[3][0]) / cols, (r + v[3][1]) / rows)
        me.materials.append(mat)
        if cutout:  # those sets' triangles -> the template's alpha-tested material
            cmat = mat.copy()
            cmat.name, cmat["lp2_mat"] = f"{set_id}_{part}_mat{tcut[part]:03d}", tcut[part]
            me.materials.append(cmat)
            for poly in me.polygons:
                if verts[poly.vertices[0]][5] in cutout:
                    poly.material_index = 1
        ob = bpy.data.objects.new(part if part != "body" else "torso", me)
        col.objects.link(ob)
        groups = {}
        for v in verts:
            for j, w in v[4].items():
                g = j if isinstance(j, str) else IMP.joint_name(j)
                if g not in groups:
                    groups[g] = ob.vertex_groups.new(name=g)
                groups[g].add([v[0]], w, "REPLACE" if False else "ADD")
        ob.parent = arm
        mod = ob.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        if hands:
            c, r = place["hand"]
            for src in hands["objects"]:
                h = src.copy()
                h.data = src.data.copy()
                h.name = f"{set_id}_hand_g{src['lp2_group']}"
                h.hide_render = False
                col.objects.link(h)
                for loop in h.data.uv_layers.active.data:
                    u, v = loop.uv
                    loop.uv = ((c + u) / cols, (r + v) / rows)
                for slot in h.material_slots:  # same textures, the template's own material number
                    i = int(slot.material["lp2_mat"])
                    name = f"{set_id}_{part}_mat{i:03d}"
                    m2 = bpy.data.materials.get(name) or mat.copy()
                    m2.name, m2["lp2_mat"] = name, i
                    slot.link, slot.material = "OBJECT", m2
        print(f"{part}: {len(verts)} vertices, {len(P['tris'])} triangles, {len(sets)} texture set(s) -> "
              f"{cols * cell}x{rows * cell} atlas, letters {''.join(letters)}, template material {tmat[part]}"
              + (f", cut-out sets {sorted(cutout)} -> material {tcut[part]}" if cutout else ""))

    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out_blend), compress=True)
    print("saved", out_blend)


main()
