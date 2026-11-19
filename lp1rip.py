#!/usr/bin/env python3
"""Rip a Lost Planet 1 character for the LP2 Character Importer (lp2-charedit), no Blender needed.

  lp1rip.py CODE_OR_MODEL OUT_DIR --id ID --name "Display name" [--faction FF] [--template 2900]
            [--head CODE_OR_MODEL] [--arc NAME] [--energy-hue DEG] [--body-groups G,G] [--drop-groups G,G]
            [--keep-hands]

CODE: an LP1 model code (hm71); it is looked up in the PC install and the 360 Colonies tree (model_index.json,
built on the first run) and extracted into OUT_DIR/.tree. --arc picks the archive when several hold it.
Writes into OUT_DIR:
  ID.obj           the whole character as ONE mesh, in LP1's T-pose and space
  ID.lp2rig.json   what the importer needs to rig it: per OBJ vertex the LP2 joint weights (LP1's own skin,
                   joints past the core skeleton folded into their core ancestor), per triangle the part slot
                   and template material, the joints to slide (where LP1 has them, in the OBJ's space), the
                   part textures and the set's id / name / faction / template.
  tex/ID_<part>_<role>.png   one atlas per part and role (BM_A-D from LP1's A-D variants, NM, MM): an LP2 part
                   wears one texture set, LP1 characters use several; the UVs are remapped into it.
The importer (OBJ import) reads the rig file, slides the stock skeleton's limb joints onto LP1's, and Bind to stock
pose then moves the mesh onto LP2's joints. Spine, chest, neck, head and feet stay where LP2 has them: a pivot
height doesn't change the body's shape (moving the mesh by those offsets bent the old ports' torso and shoulders),
and LP2 soles all sit 13 cm under the ankle joint (LP1: 7): the feet only move onto LP2's floor (the stock soles).
Hands: LP1 bakes one open hand into the arm; LP2 swaps hand meshes per pose. The LP1 hand (past the wrist) is cut
off (--keep-hands keeps it) and the export keeps the template's hands, textured from a spare atlas cell holding
the template's hand texture tinted to the LP1 glove ("hand_cell").
"""
import glob, json, math, os, re, struct, sys, zlib

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx, lp1model, lp1tex, mod2obj  # noqa: E402

RAW = os.path.expanduser("~/Projects/lp2-assets/raw/CustomParts")
INDEX = os.path.expanduser("~/Projects/lp2-assets/lp1/model_index.json")
ROOTS = [os.path.expanduser("~/.local/share/Steam/steamapps/common/lost planet extreme condition"),
         os.path.expanduser("~/Projects/lp-isos/work/xenon")]
LP1_TO_LP2 = {0: 1, **{j: j + 1 for j in range(1, 19)}}  # core joints; LP2 inserts the pelvis
LP1_NECK, LP1_HEAD = 9, 10
PART_OF = {10: "head", 11: "head", **{j: "legs" for j in range(1, 8)}}  # by LP2 main joint; else body
PREFIX = {"head": "hd", "body": "bd", "legs": "lg"}
# LP2 joints slid onto LP1's: hips, knees, collarbones, upper arms, elbows, wrists
FIT = [2, 3, 5, 6, 12, 13, 14, 15, 16, 17, 18, 19]
KEEP = [4, 7]  # feet: stay where LP2 has them (their parent knee moves)
WRIST = {15: -1, 19: 1}  # LP2 wrist joints, by side (x sign)
HAND_GROUPS = range(200, 208)
ATLAS_MAX = 1024
CUTOUT = 0.25  # share of see-through texels that makes an LP1 colour map a cut-out


def tpl_path(part, series):
    p = PREFIX[part]
    return f"{RAW}/{p}{series}/model/hm/hm{series[:2]}/{p}{series}/{p}{series}.rModel"


def world_joints(bones):
    W, out, parent = {}, {}, {}
    for i, bn in enumerate(bones):
        m = np.array(bn["local"]).reshape(4, 4)
        W[i] = m if bn["parent"] == 255 else m @ W[bn["parent"]]
        out[bn["joint"]] = W[i][3, :3]
        parent[bn["joint"]] = bones[bn["parent"]]["joint"] if bn["parent"] != 255 else None
    return out, parent


def template_info(path):
    """-> (joint world positions, joint parents, plain material, cut-out material or None, sole height)"""
    b = open(path, "rb").read()
    bones, _ = mod2obj.read_bones(b)
    Md = mod2obj.read_model(b)
    use = {}
    for m in Md["meshes"]:
        if m["mat"] < len(Md["mats"]) and tuple(Md["mats"][m["mat"]]) != (0, 0, 0):
            use[m["mat"]] = use.get(m["mat"], 0) + m["vc"]
    plain = max(use, key=use.get)
    tex_off, ntex = struct.unpack_from("<I", b, 0x2C)[0], struct.unpack_from("<I", b, 0x1C)[0]
    flags = [struct.unpack_from("<I", b, tex_off + 64 * ntex + 160 * i)[0] for i in range(len(Md["mats"]))]
    cut = next((i for i, f in enumerate(flags) if f == flags[plain] | 0x4000 and f != flags[plain]), None)
    lo = 1e9
    for m in Md["meshes"]:
        if m["lodmask"] & 1 and m["fmt"] in mod2obj.SKIN:
            g = mod2obj.mesh_geometry(b, m, Md)
            if g:
                lo = min(lo, min(p[1] for p in g[0].values()))
    pos, par = world_joints(bones)
    return pos, par, plain, cut, lo


def template_hand_uvs(series):
    b = open(tpl_path("body", series), "rb").read()
    Md = mod2obj.read_model(b)
    uvs = []
    for m in Md["meshes"]:
        if m["lodmask"] & 1 and m["fmt"] in mod2obj.SKIN and m["group"] in HAND_GROUPS:
            g = mod2obj.mesh_geometry(b, m, Md)
            if g:
                uvs += list(g[1].values())
    return uvs


# ---------------------------------------------------------------- finding + extracting LP1 models

def model_index():
    if os.path.exists(INDEX):
        return json.load(open(INDEX))
    idx = {}
    for root in ROOTS:
        for arc in sorted(glob.glob(os.path.join(root, "**", "*.arc"), recursive=True)):
            with open(arc, "rb") as f:
                if f.read(4) not in (b"ARC\0", b"\0CRA"):
                    continue
            try:
                ents = list(arcx.entries(open(arc, "rb").read()))
            except SystemExit:
                continue
            for name, *_ in ents:
                m = re.fullmatch(r"model\\hm\\(hm\w+)\\(\w+)", name, re.I)
                if m and m.group(1).lower() == m.group(2).lower() and arc not in idx.get(m.group(1).lower(), []):
                    idx.setdefault(m.group(1).lower(), []).append(arc)
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    json.dump(idx, open(INDEX, "w"), indent=0)
    return idx


def extract(arc, code, out):
    """the model's folder, plus any texture it names elsewhere in the same archive -> the model file"""
    data = open(arc, "rb").read()
    ents = list(arcx.entries(data))

    def write(name, th, cs, ds, off):
        raw = zlib.decompress(data[off:off + cs]) if cs != ds else data[off:off + cs]
        dst = os.path.join(out, *name.lower().split("\\")) + f".{th:#010x}"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(raw)
        return dst

    model = None
    for name, th, cs, ds, _f, off in ents:
        if name.lower().startswith(f"model\\hm\\{code}\\"):
            dst = write(name, th, cs, ds, off)
            if name.lower() == f"model\\hm\\{code}\\{code}" and th == 0x1041BD9E:  # the MOD, not its namesakes
                model = dst
    if model is None:
        raise SystemExit(f"{code}: no model in {arc}")
    want = {t.lower() for t in lp1model.read_model(open(model, "rb").read())["texs"]}
    for name, th, cs, ds, _f, off in ents:
        if name.lower() in want and not name.lower().startswith(f"model\\hm\\{code}\\"):
            write(name, th, cs, ds, off)
    return model


def find_model(arg, out, arc_pick=None):
    if os.path.isfile(arg):
        return arg
    code = arg.lower()
    arcs = model_index().get(code)
    if not arcs:
        raise SystemExit(f"{code}: not found in the LP1 archives ({', '.join(ROOTS)})")
    if arc_pick:
        arcs = [a for a in arcs if os.path.basename(a).lower() == arc_pick.lower()] or arcs
    return extract(arcs[0], code, os.path.join(out, ".tree"))


def load_source(path):
    b = open(path, "rb").read()
    bones = lp1model.read_bones(b)
    pos, par = world_joints(bones)

    def core(j):
        while j not in LP1_TO_LP2 and par.get(j) is not None:
            j = par[j]
        return j if j in LP1_TO_LP2 else 0

    return dict(path=path, b=b, M=lp1model.read_model(b), pos=pos, par=par, jmap={j: core(j) for j in pos},
                shift=np.zeros(3), part=None)


# ---------------------------------------------------------------- textures

def load_rgba(path):
    """LP1 texture -> float RGBA (H, W, 4), rows top-down"""
    import io
    dds = lp1tex.to_dds(lp1tex.read_tex(open(path, "rb").read()))
    return np.asarray(Image.open(io.BytesIO(dds)).convert("RGBA"), dtype=np.float32) / 255.0


def dds_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0


def rgb_normals(px):
    """PC LP1 normal maps are DXT5nm (X in alpha, Y in green); the 360's are already RGB."""
    if px[..., 0].min() < 0.98 or px[..., 2].min() < 0.98:
        return px
    x, y = px[..., 3] * 2 - 1, px[..., 1] * 2 - 1
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
    return np.dstack([px[..., 3], px[..., 1], z * 0.5 + 0.5, np.ones_like(z)]).astype(np.float32)


def energy_hue(px, hue):
    """Purple-magenta texels (LP1 energy lines) -> hue (degrees), same saturation and value."""
    rgb = px[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    h = np.degrees(np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)) % 360
    w = np.clip((sat - 0.25) / 0.15, 0, 1) * ((h >= 260) & (h <= 340)) * (mx > 0.15)
    if not w.any():
        return px
    k = lambda n: (n + hue / 60.0) % 6
    f = lambda n: mx - mx * sat * np.clip(np.minimum(k(n), 4 - k(n)), 0, 1)
    out = px.copy()
    out[..., :3] = rgb * (1 - w[..., None]) + np.dstack([f(5), f(3), f(1)]) * w[..., None]
    return out


def resize(px, s):
    if px.shape[0] == s and px.shape[1] == s:
        return px
    chans = [np.asarray(Image.fromarray(px[..., c].astype(np.float32), "F").resize((s, s), Image.BILINEAR)) for c in range(4)]
    return np.clip(np.dstack(chans), 0, 1)


def sample(px, uvs):
    """uvs bottom-up"""
    h, w = px.shape[:2]
    return np.array([px[min(h - 1, max(0, int((1 - v) * h))), min(w - 1, max(0, int(u * w)))] for u, v in uvs])


def hand_texture(series, role, hand_uvs, glove):
    """the template body's hand texture for one role; colour maps tinted to the LP1 glove colour"""
    stem = f"bd{series}"
    d = f"{RAW}/{stem}/model/hm/hm{series[:2]}/{stem}"
    if role == "NM":
        px = dds_rgba(f"{d}/{stem}_NM-00.dds")
        x, y = px[..., 3] * 2 - 1, px[..., 1] * 2 - 1
        z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
        return np.dstack([px[..., 3], px[..., 1], z * 0.5 + 0.5, np.ones_like(z)]).astype(np.float32)
    if role == "MM":
        return dds_rgba(f"{d}/{stem}_MM-00.dds")
    letter = role[-1]
    k = "ABCD".index(letter)
    path = f"{RAW}/{stem}{k:02d}/model/hm/hm{series[:2]}/{stem}/{stem}_BM-00_{letter}.dds"
    if not os.path.exists(path):
        path = f"{RAW}/{stem}00/model/hm/hm{series[:2]}/{stem}/{stem}_BM-00_A.dds"
    px = dds_rgba(path)
    if glove is None:
        return px
    lum = px[..., :3] @ np.array([0.299, 0.587, 0.114])
    ref = sample(px, hand_uvs)[:, :3] @ np.array([0.299, 0.587, 0.114])
    out = px.copy()
    out[..., :3] = np.clip((lum / max(1e-3, float(np.mean(ref))))[..., None] * glove, 0, 1)
    return out


# ---------------------------------------------------------------- main

def main():
    argv = sys.argv[1:]
    opts, pos_args, i = {}, [], 0
    flags = {"--keep-hands"}
    while i < len(argv):
        if argv[i] in flags:
            opts[argv[i]] = True
            i += 1
        elif argv[i].startswith("--"):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            pos_args.append(argv[i])
            i += 1
    if len(pos_args) != 2 or "--id" not in opts or "--name" not in opts:
        raise SystemExit(__doc__)
    src_arg, out = pos_args
    out = os.path.abspath(out)
    set_id, series = opts["--id"], opts.get("--template", "2900")
    os.makedirs(os.path.join(out, "tex"), exist_ok=True)
    body_groups = {int(g) for g in opts.get("--body-groups", "").split(",") if g}
    drop_groups = {int(g) for g in opts.get("--drop-groups", "").split(",") if g}
    hue = float(opts["--energy-hue"]) if "--energy-hue" in opts else None

    srcs = [load_source(find_model(src_arg, out, opts.get("--arc")))]
    p1 = srcs[0]["pos"]
    if "--head" in opts:
        h = load_source(find_model(opts["--head"], out))
        root = next(j for j, pj in h["par"].items() if pj is None)
        h["jmap"] = {j: LP1_NECK if j == root else LP1_HEAD for j in h["pos"]}
        h["shift"] = p1[LP1_NECK] - h["pos"][root]
        h["part"] = "head"
        srcs.append(h)

    info = {part: template_info(tpl_path(part, series)) for part in PREFIX}
    p2, par2 = {}, {}
    for part in PREFIX:
        p2.update(info[part][0])
        par2.update(info[part][1])
    allowed = {part: set(info[part][0]) for part in PREFIX}
    floor = info["legs"][4]

    def to_allowed(j, part):
        while j is not None and j not in allowed[part]:
            j = par2.get(j)
        return j if j is not None else 1

    # ---- triangles
    verts, vkey = [], {}  # vertex: (pos, nrm, uv (LP1, bottom-up), weights {LP2 joint: w}, texture set, part)
    tris, tri_part, tri_set = [], [], []
    hand_tris = []  # (texture set, [uv x3]) of the cut-off LP1 hands
    jobs = [(si, s, m) for si, s in enumerate(srcs) for m in s["M"]["meshes"]
            if s["M"]["mats"][m["mat"]][0] and m["lodmask"] & 1 and not (si == 0 and m["group"] in drop_groups)]
    for si, s, m in jobs:
        b, M = s["b"], s["M"]
        tset = (si, M["mats"][m["mat"]][0])
        for t in lp1model.mesh_geometry(b, M, m):
            vs = []
            for k in t:
                p, n, uv, sk = lp1model.vertex(b, M, m, k)
                vs.append((np.array(p) + s["shift"], n, uv, [(s["jmap"][j], w) for j, w in sk]))
            score = {}
            for v in vs:
                for j, w in v[3]:
                    score[LP1_TO_LP2[j]] = score.get(LP1_TO_LP2[j], 0) + w
            main = max(score, key=score.get)
            part = s["part"] or ("body" if m["group"] in body_groups else PART_OF.get(main, "body"))
            if main in WRIST and "--keep-hands" not in opts:
                wrist = p1[[j for j, j2 in LP1_TO_LP2.items() if j2 == main][0]]
                if sum(v[0][0] for v in vs) / 3 * WRIST[main] > abs(wrist[0]) - 1.0:
                    hand_tris.append((tset, [v[2] for v in vs]))
                    continue
            ids = []
            for k, (p, n, uv, sk) in zip(t, vs):
                key = (si, m["voff"], k, tset, part)
                if key not in vkey:
                    ws = {}
                    for j, w in sk:
                        ja = to_allowed(LP1_TO_LP2[j], part)
                        ws[ja] = ws.get(ja, 0.0) + w
                    vkey[key] = len(verts)
                    verts.append([p, n, uv, ws, tset, part])
                ids.append(vkey[key])
            tris.append(ids)
            tri_part.append(part)
            tri_set.append(tset)

    # ---- joints to slide; the feet sit where LP2 has them, raised by the gap between her soles and LP2's floor,
    # so Bind lowers the feet (only) onto the floor and the body keeps LP1's height (its neck / head match LP2's)
    lowest = min(v[0][1] for v in verts)
    shift = np.array([0.0, floor - lowest, 0.0])
    joints = {}
    for j1, j2 in LP1_TO_LP2.items():
        if j2 in FIT and j1 in p1:
            joints[j2] = [round(float(c), 3) for c in p1[j1]]
    for j2 in KEEP:
        joints[j2] = [round(float(c), 3) for c in p2[j2] - shift]

    # ---- atlases per part
    def tex_name(tset, slot):
        s = srcs[tset[0]]
        return lp1model.find_tex(s["path"], s["M"]["texs"][slot - 1]) if slot else None

    def tex_file(tset, letter=None):
        s = srcs[tset[0]]
        name = s["M"]["texs"][tset[1] - 1]
        if letter:
            name = re.sub(r"_[A-D]$", "", name) + "_" + letter
        return lp1model.find_tex(s["path"], name)

    uv_out = [None] * len(verts)
    tri_mat = [-1] * len(tris)
    parts_cfg, report = {}, []
    hand_uvs = template_hand_uvs(series) if hand_tris else []
    for part in PREFIX:
        mine = [k for k, p in enumerate(tri_part) if p == part]
        if not mine:
            continue
        sets = sorted({tri_set[k] for k in mine})
        cells = sets + (["hand"] if part == "body" and hand_tris else [])
        cols = 1 << math.ceil(math.log2(math.ceil(math.sqrt(len(cells))))) if len(cells) > 1 else 1
        rows = 1 << math.ceil(math.log2(math.ceil(len(cells) / cols))) if len(cells) > cols else 1
        cell = min(512, ATLAS_MAX // max(cols, rows))
        place = {s: (k % cols, k // cols) for k, s in enumerate(cells)}  # (col, row from the top)
        letters = [L for L in "ABCD" if any(tex_file(s, L) for s in sets)] or ["A"]
        mat_slots = {s: next(mm for mm in srcs[s[0]]["M"]["mats"] if mm[0] == s[1]) for s in sets}
        roles = {f"BM_{L}": [(s, tex_file(s, L) or tex_file(s, "A") or tex_file(s)) for s in sets] for L in letters}
        roles["NM"] = [(s, tex_name(s, mat_slots[s][1])) for s in sets]
        roles["MM"] = [(s, tex_name(s, mat_slots[s][2])) for s in sets]
        cutout, files = set(), {}
        lp1_bm = {}
        for role, fl in roles.items():
            atlas = np.zeros((rows * cell, cols * cell, 4), dtype=np.float32)
            atlas[...] = (0.5, 0.5, 1.0, 1.0) if role == "NM" else (0, 0, 0, 1)
            px_of = {}
            for s, f in fl:
                if not f:
                    continue
                c, r = place[s]
                px = load_rgba(f)
                if hue is not None and role.startswith("BM"):
                    px = energy_hue(px, hue)
                if role == "NM":
                    px = rgb_normals(px)
                px_of[s] = px
                atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = resize(px, cell)
                if role == "BM_A" and info[part][3] is not None and (px[..., 3] < 0.5).mean() > CUTOUT:
                    cutout.add(s)
            if role == "BM_A":
                lp1_bm = px_of
            if "hand" in place:
                glove = None
                if role.startswith("BM"):
                    cs = [c for s, uv3 in hand_tris if s in px_of for c in sample(px_of[s], uv3)]
                    glove = np.mean(cs, 0)[:3] if cs else None
                c, r = place["hand"]
                atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = resize(hand_texture(series, role, hand_uvs, glove), cell)
            if role != "NM":
                keep = atlas[..., 3].copy()
                atlas[..., 3] = 1.0  # LP1 keeps masks in alpha; LP2 would read it as transparency
                if role.startswith("BM"):
                    for s in cutout:
                        c, r = place[s]
                        atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell, 3] = keep[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell]
            path = os.path.join(out, "tex", f"{set_id}_{part}_{role}.png")
            Image.fromarray((np.clip(atlas, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(path)
            files[role] = path
        for k in mine:
            for vi in tris[k]:
                v = verts[vi]
                c, r = place[v[4]]
                uv_out[vi] = ((c + v[2][0]) / cols, (rows - 1 - r + v[2][1]) / rows)
            if tri_set[k] in cutout:
                tri_mat[k] = info[part][3]
        pc = {"textures": files, "mat": info[part][2]}
        if "hand" in place:
            c, r = place["hand"]
            pc["hand_cell"] = [c, rows - 1 - r, cols, rows]  # bottom-up cell: uv' = ((c + u) / cols, (r + v) / rows)
        parts_cfg[part] = pc
        report.append(f"{part}: {len(mine)} triangles, {len(sets)} texture set(s) -> {cols * cell}x{rows * cell} atlas, "
                      f"letters {''.join(letters)}" + (f", cut-out sets -> material {info[part][3]}" if cutout else ""))
    _ = lp1_bm

    # ---- write
    obj = os.path.join(out, f"{set_id}.obj")
    with open(obj, "w") as f:
        f.write(f"# lp1rip.py {os.path.basename(srcs[0]['path'])}: LP1 T-pose, cm; rig in {set_id}.lp2rig.json\n")
        f.write(f"o {set_id}\n")
        for v in verts:
            f.write("v %.4f %.4f %.4f\n" % tuple(v[0]))
        for k, v in enumerate(verts):
            f.write("vt %.6f %.6f\n" % (uv_out[k] if uv_out[k] else (0.0, 0.0)))
        for v in verts:
            n = np.array(v[1], dtype=float)
            n = n / max(1e-9, float(np.linalg.norm(n)))
            f.write("vn %.4f %.4f %.4f\n" % tuple(n))
        for t in tris:
            f.write("f " + " ".join(f"{k + 1}/{k + 1}/{k + 1}" for k in t) + "\n")
    rig = dict(format="lp2rig", version=1, source=[s["path"] for s in srcs], template=series,
               floor_shift=round(float(shift[1]), 3),
               meta=dict(id=set_id, name=opts["--name"], faction=opts.get("--faction", "ALL")),
               joints={str(j): p for j, p in sorted(joints.items())},
               weights=[[[j, round(w, 4)] for j, w in sorted(v[3].items()) if w > 0] for v in verts],
               tri_part=tri_part, tri_mat=tri_mat, parts=parts_cfg)
    json.dump(rig, open(os.path.join(out, f"{set_id}.lp2rig.json"), "w"))
    print(f"{set_id}: {len(verts)} vertices, {len(tris)} triangles, {len(hand_tris)} hand triangles cut, "
          f"soles {lowest:.1f}, LP2 floor {floor:.1f}: the feet move {shift[1]:+.1f} cm in Bind")
    for line in report:
        print("  " + line)
    for j2 in FIT:
        if j2 in joints:
            d = np.array(joints[j2]) - p2[j2]
            print(f"  j{j2:02d}: LP1 {np.round(joints[j2], 1)} vs LP2 {np.round(p2[j2], 1)} (off {np.linalg.norm(d):.1f} cm)")
    print(obj)


if __name__ == "__main__":
    main()
