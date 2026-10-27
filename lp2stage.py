#!/usr/bin/env python3
"""Lost Planet 1 (Colonies, 360) stage models -> one Lost Planet 2 stage rModel + rTextures.

  lp2stage.py --template LP2_STAGE.rModel --out DIR --tex-dir 'scr\\Online\\online00' LP1_STAGE ...

Writes DIR/<tex-dir>/<name>.rModel (name = the template's) and every texture beside it, laid out
for arcx.pack. The template (a stock LP2 stage model, e.g. online00) gives the material block that
the area's shader package was built for, and its CM (environment cube) texture name.

LP2 static stage format 0x49B4F022, 28 bytes: f32 xyz (cm), normal u8x4 (+12, bias 127, w 0xff),
tangent u8x4 (+16), uv f16x2 (+20), RGBA8 baked light (+24). LP1 bakes light into _LM textures
(vertex +28 = lightmap uv); it is sampled into the vertex colour here. LP1 and LP2 share the space
(cm, Y up), so positions are copied.
Model: header 0x80 (counts, offsets, bsphere 0x40, bbox 0x50/0x60, (1000, 3000, 1, 0) at 0x70),
groups 32 B (u32 id, 12 pad, sphere) = one per mesh, textures 64 B, materials 160 B, meshes 48 B,
u32 count + 144 B box per mesh (u32 255, 12 pad, sphere, min, max, 4x4 frame, half extents),
vertex buffer, u16 triangle lists (absolute within a 64K window; the window moves by mesh +0x10).
"""
import argparse, os, struct, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp1model, lp1tex, lp2tex  # noqa: E402

FMT = 0x49B4F022
STRIDE = 28


def unpack1010(w):
    return np.array([((((w >> s) & 0x3FF) ^ 0x200) - 0x200) / 511.0 for s in (0, 10, 20)])


def u8n(v):
    v = np.asarray(v, float)
    l = np.linalg.norm(v) or 1.0
    return bytes(int(round(x / l * 127 + 127)) for x in v) + b"\xff"


def tex_rgba(path):
    """LP1 texture file -> RGBA uint8 array (top row first)."""
    import io
    from PIL import Image
    t = lp1tex.read_tex(open(path, "rb").read())
    if t.get("rgba") is not None:
        return np.frombuffer(t["rgba"], np.uint8).reshape(t["h"], t["w"], 4)
    code = struct.unpack("<I", t["fourcc"])[0] if t.get("fourcc") else 0
    if code in (21, 22):  # PC: D3DFMT A8R8G8B8 / X8R8G8B8 (BGRA bytes) instead of a DXT FourCC
        img = np.frombuffer(t["data"], np.uint8, t["w"] * t["h"] * 4).reshape(t["h"], t["w"], 4)[..., [2, 1, 0, 3]].copy()
        if code == 22:
            img[..., 3] = 255
        return img
    return np.asarray(Image.open(io.BytesIO(lp1tex.to_dds(t))).convert("RGBA"))


def pot(img):
    """Power-of-two sides (lp2tex needs them); stage textures normally are already."""
    h, w = img.shape[:2]
    H, W = 1 << max(2, (h - 1).bit_length()), 1 << max(2, (w - 1).bit_length())
    if (H, W) == (h, w):
        return img
    from PIL import Image
    return np.asarray(Image.fromarray(img).resize((W, H)))


def write_stage(dst, textures, materials, meshes):
    """Write a static stage rModel. meshes: [dict(mat, verts (n, 28) u8 rows (or a list of 28 B), tris [(a, b, c)])]"""
    meshes = [dict(mat=m["mat"], verts=np.frombuffer(b"".join(m["verts"]), np.uint8).reshape(-1, STRIDE)
                   if isinstance(m["verts"], list) else np.asarray(m["verts"], np.uint8),
                   tris=np.asarray(m["tris"], np.int64).reshape(-1, 3)) for m in meshes]
    meshes = [m for m in meshes if len(m["tris"])]
    for m in meshes:
        p = m["verts"][:, :12].copy().view("<f4").reshape(-1, 3)
        m["lo"], m["hi"] = p.min(0).astype(np.float64), p.max(0).astype(np.float64)
    # windows of <= 65535 vertices; a mesh too big for one window is split by triangles
    parts = []
    for m in meshes:
        if len(m["verts"]) <= 65535:
            parts.append(m)
            continue
        cur, rm = [], {}
        for t in m["tris"].tolist() + [None]:
            if t is None or len(rm) + 3 > 65535:
                vs = sorted(rm, key=rm.get)
                parts.append(dict(m, verts=m["verts"][vs], tris=np.array([[rm[i] for i in tt] for tt in cur], np.int64).reshape(-1, 3)))
                cur, rm = [], {}
                if t is None:
                    break
            for i in t:
                rm.setdefault(i, len(rm))
            cur.append(t)
    if len(parts) > 4095:
        raise ValueError(f"{len(parts)} meshes: a stage model holds at most 4095 (12-bit group ids)")
    vb, ib, recs = bytearray(), bytearray(), []
    win_off, win_n, total = 0, 0, 0
    for k, m in enumerate(parts):
        n = len(m["verts"])
        if win_n + n > 65535:
            win_off, win_n = total * STRIDE, 0
        vstart = win_n
        vb += m["verts"].tobytes()
        istart = len(ib) // 2
        ib += (m["tris"] + vstart).astype("<u2").tobytes()
        recs.append(dict(m, vstart=vstart, voff=win_off, istart=istart, icount=len(m["tris"]) * 3))
        win_n += n
        total += n

    lo = np.min([m["lo"] for m in parts], 0)
    hi = np.max([m["hi"] for m in parts], 0)
    centre, radius = (lo + hi) / 2, float(np.linalg.norm(hi - lo) / 2)
    groups = b"".join(struct.pack("<I12x4f", k + 1, *((m["lo"] + m["hi"]) / 2), float(np.linalg.norm(m["hi"] - m["lo"]) / 2))
                      for k, m in enumerate(recs))
    tex_block = b"".join(struct.pack("<64s", t.encode()) for t in textures)
    mat_block = b"".join(materials)
    mesh_block = bytearray()
    for k, m in enumerate(recs):
        n = len(m["verts"])
        mesh_block += struct.pack("<HHIBBBBIIIIIIBBHHHI", 0xFDF7, n, (k + 1) | m["mat"] << 12 | 0xFF << 24, 1, 0, STRIDE, 3,
                                  m["vstart"], m["voff"], FMT, m["istart"], m["icount"], 0, 1, 0, k + 1,
                                  m["vstart"], m["vstart"] + n - 1, 0)
    boxes = bytearray(struct.pack("<I", len(recs)))
    for m in recs:
        c, h = (m["lo"] + m["hi"]) / 2, (m["hi"] - m["lo"]) / 2
        boxes += struct.pack("<I12x4f4f4f16f4f", 255, *c, float(np.linalg.norm(h)), *m["lo"], 0.0, *m["hi"], 0.0,
                             1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *c, 1.0, *h, 0.0)
    o_grp = 0x80
    o_tex = o_grp + len(groups)
    o_mesh = o_tex + len(tex_block) + len(mat_block)
    o_vb = o_mesh + len(mesh_block) + len(boxes)
    o_ib = o_vb + len(vb)
    head = struct.pack("<4sHHHH13I", b"MOD\0", 0xC5, 0, len(recs), len(materials), total, len(ib) // 2,
                       len(ib) // 6, len(vb), len(textures), len(recs), 0, o_grp, o_tex, o_mesh, o_vb, o_ib, 0)
    head += struct.pack("<4f4f4f4I", *centre, radius, *lo, 0.0, *hi, 0.0, 1000, 3000, 1, 0)
    assert len(head) == 0x80
    data = head + groups + tex_block + mat_block + mesh_block + boxes + vb + ib
    open(dst, "wb").write(data)
    return data


def balance(meshes, amount):
    """per-channel gains on the baked light (vertex +24) so its average colour is grey, by amount (0..1)"""
    cols = np.array([list(v[24:27]) for m in meshes for v in m["verts"]], np.float64)
    if not len(cols):
        return
    mean = cols.mean(0)
    gain = 1 + amount * (mean.mean() / np.maximum(mean, 1) - 1)
    for m in meshes:
        out = []
        for v in m["verts"]:
            c = bytes(int(min(255, round(x * g))) for x, g in zip(v[24:27], gain))
            out.append(v[:24] + c + v[27:])
        m["verts"] = out
    print(f"baked light balanced: average {mean.round(1).tolist()} -> gains {gain.round(3).tolist()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tex-dir", required=True, help="archive folder of the model, e.g. scr\\Online\\online00")
    ap.add_argument("--prefix", default="lp1", help="texture name prefix")
    ap.add_argument("--light", type=float, default=1.0, help="lightmap -> vertex colour scale")
    ap.add_argument("--balance", type=float, default=0.0,
                    help="white balance of the baked light, 0..1: 1 scales each channel so the average is grey "
                         "(LP1 lightmaps carry their map's colour cast)")
    ap.add_argument("--empty", action="append", default=[], metavar="NAME",
                    help="also write NAME.rModel holding one tiny triangle (stand-in for a stock model the area still loads)")
    ap.add_argument("models", nargs="+")
    a = ap.parse_args()

    tb = open(a.template, "rb").read()
    t_ntex = struct.unpack_from("<I", tb, 0x1C)[0]
    t_tex = struct.unpack_from("<I", tb, 0x2C)[0]
    t_names = [tb[t_tex + i * 64:t_tex + i * 64 + 64].split(b"\0")[0].decode() for i in range(t_ntex)]
    mat_tpl = bytearray(tb[t_tex + t_ntex * 64:t_tex + t_ntex * 64 + 160])
    cm_name = t_names[struct.unpack_from("<I", mat_tpl, 36)[0] - 1]
    model_name = os.path.splitext(os.path.basename(a.template))[0]
    out_dir = os.path.join(a.out, *a.tex_dir.split("\\"))
    os.makedirs(out_dir, exist_ok=True)

    textures = [cm_name]  # LP2 texture list (1-based in materials)
    tex_index, converted = {cm_name: 1}, {}

    def add_tex(src_path, name, kind):
        full = a.tex_dir + "\\" + name
        if full not in tex_index:
            if src_path is None:  # flat stand-ins
                img = np.zeros((4, 4, 4), np.uint8)
                img[...] = (128, 128, 255, 255) if kind == "nm" else (0, 0, 0, 255)
            else:
                img = pot(tex_rgba(src_path))
                if kind == "bm" and img[..., 3].max() < 8:
                    # alpha zero everywhere is not transparency (LP1 keeps a mask there, e.g. most of s900's
                    # colour maps): opaque, so DXT1 and nothing for the game to cut away
                    img = img.copy()
                    img[..., 3] = 255
            open(os.path.join(out_dir, name + ".rTexture"), "wb").write(lp2tex.encode(img, kind))
            textures.append(full)
            tex_index[full] = len(textures)
        return tex_index[full]

    materials, mat_key = [], {}
    meshes = []  # dict(mat, verts bytes list, tris)
    lm_cache = {}
    for path in a.models:
        b = open(path, "rb").read()
        M = lp1model.read_model(b)
        E = M["e"]
        tex_off = struct.unpack_from(E + "I", b, 0x34)[0]
        mo = tex_off + len(M["texs"]) * 64
        texp = [lp1model.find_tex(path, t) for t in M["texs"]]
        for mi, m in enumerate(M["meshes"]):
            print(f"@progress {(mi + 1) / len(M['meshes']):.3f} {os.path.basename(path).split('.')[0]}: meshes and lightmaps", flush=True)
            w = struct.unpack_from(E + "40I", b, mo + m["mat"] * 160)
            slot = lambda j: w[j] - 1 if 0 < w[j] <= len(texp) and texp[w[j] - 1] else None
            if not m["lodmask"] & 1 or slot(6) is None:
                continue
            key = (texp[slot(6)], slot(7) is not None and texp[slot(7)], slot(8) is not None and texp[slot(8)])
            if key not in mat_key:
                nm = lambda s: os.path.basename(texp[s]).rsplit(".", 1)[0]
                bm = add_tex(texp[slot(6)], f"{a.prefix}_{nm(slot(6))}", "bm")
                nrm = add_tex(texp[slot(7)], f"{a.prefix}_{nm(slot(7))}", "nm") if slot(7) is not None else add_tex(None, f"{a.prefix}_flat_NM", "nm")
                mm = add_tex(texp[slot(8)], f"{a.prefix}_{nm(slot(8))}", "mm") if slot(8) is not None else add_tex(None, f"{a.prefix}_none_MM", "mm")
                mat = bytearray(mat_tpl)
                struct.pack_into("<3I", mat, 12, bm, nrm, mm)
                struct.pack_into("<I", mat, 36, 1)
                materials.append(bytes(mat))
                mat_key[key] = len(materials) - 1
            lm = None
            if slot(9) is not None:
                p = texp[slot(9)]
                if p not in lm_cache:
                    lm_cache[p] = tex_rgba(p).astype(np.float32)
                lm = lm_cache[p]
            tris = lp1model.mesh_geometry(b, M, m)
            used = sorted({i for t in tris for i in t})
            remap = {v: n for n, v in enumerate(used)}
            vbytes = []
            for i in used:
                o = M["vb"] + m["voff"] + i * 32
                pos = struct.unpack_from(E + "3f", b, o)
                n = unpack1010(struct.unpack_from(E + "I", b, o + 12)[0])
                tg = unpack1010(struct.unpack_from(E + "I", b, o + 16)[0])
                uv = struct.unpack_from(E + "2e", b, o + 20)
                lu, lv = struct.unpack_from(E + "2e", b, o + 28)
                if lm is not None and np.isfinite(lu) and np.isfinite(lv):
                    h, wd = lm.shape[:2]
                    px = lm[min(h - 1, max(0, int(lv * h))), min(wd - 1, max(0, int(lu * wd)))]  # clamp, no wrap
                    col = bytes(int(min(255, x * a.light)) for x in px[:3]) + b"\xff"
                else:
                    col = b"\x80\x80\x80\xff"
                vbytes.append(struct.pack("<3f", *pos) + u8n(n) + u8n(tg) + struct.pack("<2e", *uv) + col)
            pts = np.array([struct.unpack_from("<3f", v) for v in vbytes])
            meshes.append(dict(mat=mat_key[key], verts=vbytes, tris=[tuple(remap[i] for i in t) for t in tris],
                               lo=pts.min(0), hi=pts.max(0)))
        print(f"{os.path.basename(path)}: {len(meshes)} meshes so far, {len(textures)} textures")

    if a.balance > 0:
        balance(meshes, a.balance)
    dst = os.path.join(out_dir, model_name + ".rModel")
    data = write_stage(dst, textures, materials, meshes)
    total = sum(len(m["verts"]) for m in meshes)
    ntri = sum(len(m["tris"]) for m in meshes)
    for name in a.empty:  # same layout, one 1 mm triangle far below the map, first material
        v = [struct.pack("<3f", x, -100000.0, z) + b"\x7f\xff\x7f\xff" * 2 + struct.pack("<2e", 0, 0) + b"\0\0\0\xff"
             for x, z in ((0, 0), (0.1, 0), (0, 0.1))]
        m = dict(lo=np.array([0, -100000.0, 0]), hi=np.array([0.1, -100000.0, 0.1]))
        g = struct.pack("<I12x4f", 1, 0.05, -100000.0, 0.05, 0.1)
        mesh = struct.pack("<HHIBBBBIIIIIIBBHHHI", 0xFDF7, 3, 1 | 0xFF << 24, 1, 0, STRIDE, 3, 0, 0, FMT, 0, 3, 0, 1, 0, 1, 0, 2, 0)
        c, h = (m["lo"] + m["hi"]) / 2, (m["hi"] - m["lo"]) / 2
        box = struct.pack("<I", 1) + struct.pack("<I12x4f4f4f16f4f", 255, *c, 0.1, *m["lo"], 0.0, *m["hi"], 0.0,
                                                 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *c, 1.0, *h, 0.0)
        tb1 = struct.pack("<64s", textures[0].encode()) + struct.pack("<64s", textures[1].encode())
        e_tex = 0x80 + 32
        e_mesh = e_tex + len(tb1) + 160
        e_vb = e_mesh + 48 + len(box)
        e_ib = e_vb + 3 * STRIDE
        hd = struct.pack("<4sHHHH13I", b"MOD\0", 0xC5, 0, 1, 1, 3, 3, 1, 3 * STRIDE, 2, 1, 0, 0x80, e_tex, e_mesh, e_vb, e_ib, 0)
        hd += struct.pack("<4f4f4f4I", *c, 0.1, *m["lo"], 0.0, *m["hi"], 0.0, 1000, 3000, 1, 0)
        mat = bytearray(materials[0])
        struct.pack_into("<3I", mat, 12, 2, 2, 2)
        open(os.path.join(out_dir, name + ".rModel"), "wb").write(hd + g + tb1 + bytes(mat) + mesh + box + b"".join(v) + struct.pack("<3H", 0, 1, 2))
        print(f"wrote stand-in {name}.rModel")
    print(f"wrote {dst}: {len(meshes)} meshes, {len(materials)} materials, {len(textures)} textures, {total} vertices, "
          f"{ntri} triangles, {len(data) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
