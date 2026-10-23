#!/usr/bin/env python3
"""Sky domes for map packages: a stock map's sky, or a dome from a panorama image.

  lp2sky.py --game LP2_DIR stock NN OUT_DIR [--preview SKY.png]
  lp2sky.py --game LP2_DIR panorama IMAGE OUT_DIR [--centre X,Y,Z] [--brightness B] [--preview SKY.png]
  lp2sky.py --game LP2_DIR list                         stock maps with a sky model, as JSON

Stock skies are small rModels beside the stage (online03-sky, a405-sky...: format 0x207D6030, 24 B vertices: f32 xyz,
normal u8 x4, uv f16 x2, RGBA8 colour = the sky's brightness) drawn as scene models of the map's Scr scheduler with
mLightGroup 0 (no lighting). Map 00 has none of its own, so the package puts the sky in a stock scene model slot that
is otherwise a stub (online00_car1, lp2mapc.SKY_SLOT): OUT_DIR/online00_car1.rModel plus its textures, renamed into the
stage folder (STAGE_DIR\\sky_*), so the package carries them.
A panorama (equirectangular, 2:1, top row = straight up) becomes a dome of radius RADIUS cm around --centre from 15
degrees below the horizon to the top, with a405-sky's (Dual Complex) material, so it draws like a stock sky; only the
part of the image above -15 degrees is kept (texture up to 2048 x 1024).
--preview writes an equirectangular PNG of the sky for the editor's background, in Godot's panorama layout (u 0.5 looks
along -Z, 0.75 along +X; the dome uses the same, so the editor shows each direction where the game does).
"""
import argparse, io, json, math, os, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2mapc, lp2preview, lp2tex, mod2obj  # noqa: E402

FMT, STRIDE = 0x207D6030, 24
TEMPLATE = ("06", "a405-sky")   # the custom dome's material and model conventions
RADIUS = 450000.0                 # cm (a405-sky: 4.5 km)
BELOW = 15.0                      # degrees under the horizon the dome reaches
NAMES = {"00": "Desecration", "01": "Turbulent Jungle", "02": "Kraftwerk", "03": "The Great Outdoors",
         "04": "Dockyard Battle", "05": "Thunderpeal Precipice", "06": "Dual Complex", "07": "NEOS", "08": "Helix",
         "09": "Friction", "10": "Pirate Fortress", "11": "Back to the Island", "12": "Cube", "15": "Frozen Wasteland"}


def scr_arc(game, num):
    return os.path.join(game, "nativePC", "arcLp2Xml", "autoArc", f"aArea_ONLINE_{num}_scr.arc")


def sky_models(game):
    """{map number: (model path, bytes, {texture name: bytes})} for stock maps with a sky model"""
    import glob
    out = {}
    for arc in sorted(glob.glob(scr_arc(game, "*"))):
        num = os.path.basename(arc)[13:15]
        ent = lp2mapc.entries(arc)
        texs = {n.lower(): d for n, d in ent.get("rTexture", [])}
        for n, b in ent.get("rModel", []):
            leaf = lp2mapc.base(n).lower()
            if leaf.endswith("-sky") or leaf.endswith("_sky"):
                out[num] = (n, b, texs)
    return out


def model_textures(b):
    nt, ot = struct.unpack_from("<I", b, 0x1C)[0], struct.unpack_from("<I", b, 0x2C)[0]
    return ot, [b[ot + i * 64:ot + i * 64 + 64].split(b"\0")[0].decode() for i in range(nt)]


def stock(game, num, out_dir):
    """copy map num's sky model and its textures into out_dir (as lp2mapc.SKY_SLOT) -> [texture files]"""
    skies = sky_models(game)
    if num not in skies:
        raise SystemExit(f"map {num} has no sky model (have: {', '.join(sorted(skies))})")
    _, b, texs = skies[num]
    b = bytearray(b)
    ot, names = model_textures(b)
    files = []
    for i, n in enumerate(names):
        leaf = "sky_" + n.split("\\")[-1]
        new = lp2mapc.STAGE_DIR + "\\" + leaf
        if len(new) >= 64:
            raise SystemExit(f"{new}: texture name too long")
        struct.pack_into("<64s", b, ot + i * 64, new.encode())
        data = texs.get(n.lower())
        if data is None:
            print(f"  {n}: not in the map's archive (the sky draws without it)")
            continue
        p = os.path.join(out_dir, leaf + ".rTexture")
        open(p, "wb").write(data)
        files.append(p)
    open(os.path.join(out_dir, lp2mapc.SKY_SLOT + ".rModel"), "wb").write(bytes(b))
    return files


def dome(centre, brightness, rings=14, segs=48):
    """vertices (n, 24 B) and triangles of a dome from -BELOW degrees to the top; u round, v top -> bottom"""
    rows = []
    els = np.linspace(90.0, -BELOW, rings + 1)
    for el in els:
        e = math.radians(el)
        for k in range(segs + 1):   # the seam column twice (u 0 and 1)
            a = 2 * math.pi * k / segs - math.pi   # u -> direction as Godot's panorama sky maps it (u 0.5 = -Z)
            d = np.array([math.cos(e) * math.sin(a), math.sin(e), -math.cos(e) * math.cos(a)])
            rows.append((centre + RADIUS * d, -d, (k / segs, (90.0 - el) / (90.0 + BELOW))))
    v = np.zeros((len(rows), STRIDE), np.uint8)
    c = int(np.clip(round(134 * brightness), 0, 255))   # a405-sky's vertex colours are about 134
    for i, (p, n, uv) in enumerate(rows):
        v[i, :12] = np.frombuffer(struct.pack("<3f", *p), np.uint8)
        v[i, 12:16] = [int(round(x * 127 + 127)) for x in n] + [255]
        v[i, 16:20] = np.frombuffer(np.array(uv, "<f2").tobytes(), np.uint8)
        v[i, 20:24] = [c, c, c, 255]
    tris = []
    w = segs + 1
    for r in range(rings):
        for k in range(segs):
            a, b, cc, d = r * w + k, r * w + k + 1, (r + 1) * w + k, (r + 1) * w + k + 1
            tris += [(a, cc, b), (b, cc, d)]   # facing the inside (seen from the centre: counter-clockwise)
    return v, np.array(tris, np.int64)


def write_dome(template, dst, texture, verts, tris):
    """a dome model in the template sky model's layout (one mesh, one material, one texture)"""
    t = template
    h = list(struct.unpack_from("<4sHHHH13I", t, 0))
    o_grp, o_tex, o_mesh = h[12], h[13], h[14]
    nt = struct.unpack_from("<I", t, 0x1C)[0]
    if h[3] != 1 or nt != 1:
        raise SystemExit("the template sky has more than one mesh / texture")
    group = bytearray(t[o_grp:o_tex])
    mat = t[o_tex + 64:o_mesh]
    rec = bytearray(t[o_mesh:o_mesh + 48])
    P = verts[:, :12].copy().view("<f4").reshape(-1, 3).astype(np.float64)
    lo, hi = P.min(0), P.max(0)
    c, half = (lo + hi) / 2, (hi - lo) / 2
    radius = float(np.linalg.norm(half))
    struct.pack_into("<4f", group, 16, *c, radius)
    f = list(struct.unpack("<HHIBBBBIIIIIIBBHHHI", rec))
    f[1], f[11], f[17] = len(verts), len(tris) * 3, len(verts) - 1
    rec = struct.pack("<HHIBBBBIIIIIIBBHHHI", *f)
    boxes = struct.pack("<I", 1) + struct.pack("<I12x4f4f4f16f4f", 255, *c, radius, *lo, 0.0, *hi, 0.0,
                                               1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *c, 1.0, *half, 0.0)
    texb = struct.pack("<64s", texture.encode())
    vb, ib = verts.tobytes(), tris.astype("<u2").tobytes()
    o_tex2 = 0x80 + len(group)
    o_mesh2 = o_tex2 + len(texb) + len(mat)
    o_vb = o_mesh2 + len(rec) + len(boxes)
    o_ib = o_vb + len(vb)
    h[5:12] = [len(verts), len(tris) * 3, len(tris), len(vb), 1, 1, h[11]]
    h[12:17] = [0x80, o_tex2, o_mesh2, o_vb, o_ib]
    head = struct.pack("<4sHHHH13I", *h[:5], h[5], h[6], h[7], h[8], h[9], h[10], h[11], 0x80, o_tex2, o_mesh2, o_vb, o_ib, h[17])
    head += struct.pack("<4f4f4f", *c, radius, *lo, 0.0, *hi, 0.0) + t[0x70:0x80]
    data = head + bytes(group) + texb + mat + rec + boxes + vb + ib
    open(dst, "wb").write(data)


def panorama(game, image, out_dir, centre, brightness=1.0):
    from PIL import Image
    im = Image.open(image).convert("RGB")
    keep = int(round(im.height * (90.0 + BELOW) / 180.0))
    im = im.crop((0, 0, im.width, keep))
    w = 1 << min(11, max(2, round(math.log2(max(4, im.width)))))
    im = im.resize((w, w // 2), Image.LANCZOS)
    rgba = np.concatenate([np.asarray(im), np.full((im.height, im.width, 1), 255, np.uint8)], 2)
    leaf = "sky_panorama_BM"
    open(os.path.join(out_dir, leaf + ".rTexture"), "wb").write(lp2tex.encode(rgba, "bm"))
    skies = sky_models(game)
    if TEMPLATE[0] not in skies:
        raise SystemExit(f"the template sky (map {TEMPLATE[0]}) is missing")
    verts, tris = dome(np.asarray(centre, float), brightness)
    write_dome(skies[TEMPLATE[0]][1], os.path.join(out_dir, lp2mapc.SKY_SLOT + ".rModel"),
               lp2mapc.STAGE_DIR + "\\" + leaf, verts, tris)
    return [os.path.join(out_dir, leaf + ".rTexture")]


# ---------------------------------------------------------------- preview: the sky as an equirectangular image

def preview(model_path, tex_files, out_png, w=1024):
    """rasterise the sky model's triangles by direction (azimuth, elevation) from its centre, sampling its texture"""
    from PIL import Image
    b = open(model_path, "rb").read()
    M = mod2obj.read_model(b)
    _, names = model_textures(b)
    by_leaf = {os.path.basename(p)[:-len(".rTexture")].lower(): p for p in tex_files}
    h = w // 2
    img = np.zeros((h, w, 3), np.float32)
    have = np.zeros((h, w), bool)
    P_all = []
    meshes = []
    for m in M["meshes"]:
        if not m["lodmask"] & 1:
            continue
        g = mod2obj.mesh_geometry(b, m, M)
        if not g or not g[1]:
            continue
        V, U, T = g
        ids = sorted(V)
        rm = {v: i for i, v in enumerate(ids)}
        P = np.array([V[i] for i in ids])
        UV = np.array([(U[i][0], 1.0 - U[i][1]) for i in ids])
        meshes.append((m, P, UV, np.array([[rm[i] for i in t] for t in T])))
        P_all.append(P)
    if not meshes:
        raise SystemExit(f"{model_path}: no textured meshes")
    allp = np.concatenate(P_all)
    centre = np.array([(allp[:, 0].min() + allp[:, 0].max()) / 2, allp[:, 1].min(), (allp[:, 2].min() + allp[:, 2].max()) / 2])
    texcache = {}
    for m, P, UV, T in meshes:
        mats = struct.unpack_from("<12I", b, model_textures(b)[0] + len(names) * 64 + 160 * m["mat"])
        slot = mats[3]
        if not 0 < slot <= len(names):
            continue
        leaf = names[slot - 1].split("\\")[-1].lower()
        if leaf not in texcache:
            p = by_leaf.get(leaf)
            data = lp2preview.png(p, 1024) if p else None
            texcache[leaf] = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), np.float32) if data else None
        tex = texcache[leaf]
        if tex is None:
            continue
        d = P - centre
        az = np.arctan2(d[:, 0], -d[:, 2])   # Godot's panorama: u 0.5 = -Z, 0.75 = +X
        el = np.arctan2(d[:, 1], np.linalg.norm(d[:, [0, 2]], axis=1))
        X = (az / (2 * np.pi) + 0.5) * w
        Y = (0.5 - el / np.pi) * h
        for t in T:
            x, y, uv = X[t].copy(), Y[t], UV[t]
            if x.max() - x.min() > w / 2:   # crosses the seam
                x[x < w / 2] += w
            for shift in (0, -w):
                _raster(img, have, x + shift, y, uv, tex)
    if have.any():   # gaps at the top (triangles meeting at the pole): the column's first sky colour; below: the lowest
        for x in np.nonzero(have.any(0))[0]:
            first = np.argmax(have[:, x])
            img[:first, x] = img[first, x]
        rows = np.nonzero(have.any(1))[0]
        last = rows.max()
        img[last + 1:] = img[last].mean(0)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(out_png)


def _raster(img, have, x, y, uv, tex):
    h, w = have.shape
    x0, x1 = int(max(0, math.floor(x.min()))), int(min(w - 1, math.ceil(x.max())))
    y0, y1 = int(max(0, math.floor(y.min()))), int(min(h - 1, math.ceil(y.max())))
    if x0 > x1 or y0 > y1:
        return
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
    d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
    if abs(d) < 1e-9:
        return
    l0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
    l1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
    l2 = 1 - l0 - l1
    inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
    if not inside.any():
        return
    u = (l0 * uv[0, 0] + l1 * uv[1, 0] + l2 * uv[2, 0])[inside]
    v = (l0 * uv[0, 1] + l1 * uv[1, 1] + l2 * uv[2, 1])[inside]
    th, tw = tex.shape[:2]
    tx = (np.mod(u, 1.0) * tw).astype(int).clip(0, tw - 1)
    ty = (np.mod(v, 1.0) * th).astype(int).clip(0, th - 1)
    yy, xx = gy[inside].astype(int), gx[inside].astype(int)
    img[yy, xx] = tex[ty, tx]
    have[yy, xx] = True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stock")
    s.add_argument("map")
    s.add_argument("out")
    s.add_argument("--preview")
    s = sub.add_parser("panorama")
    s.add_argument("image")
    s.add_argument("out")
    s.add_argument("--centre", default="0,0,0")
    s.add_argument("--brightness", type=float, default=1.0)
    s.add_argument("--preview")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "list":
        print(json.dumps({k: NAMES.get(k, k) for k in sky_models(a.game)}))
        return
    os.makedirs(a.out, exist_ok=True)
    if a.cmd == "stock":
        files = stock(a.game, a.map.zfill(2), a.out)
        print(f"sky: map {a.map} ({NAMES.get(a.map.zfill(2), '?')}), {len(files)} textures")
    else:
        files = panorama(a.game, a.image, a.out, [float(x) for x in a.centre.split(",")], a.brightness)
        print(f"sky: panorama {os.path.basename(a.image)}")
    if a.preview and a.cmd == "panorama":
        from PIL import Image
        im = Image.open(a.image).convert("RGB")
        im.resize((1024, 512), Image.LANCZOS).save(a.preview)
        print(f"preview {a.preview}")
    elif a.preview:
        preview(os.path.join(a.out, lp2mapc.SKY_SLOT + ".rModel"), files, a.preview)
        print(f"preview {a.preview}")


if __name__ == "__main__":
    main()
