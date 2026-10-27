#!/usr/bin/env python3
"""Map Editor preview: a project's stage as a glTF binary (.glb) for the editor's viewport.

  lp2preview.py --game LP2_DIR PROJECT_DIR [--max-tex 1024]

Builds the stage the way lp2mapc.py does (lp2stage.py on the project's LP1 models, the stock map's template)
into PROJECT/.preview/stage/, splits it into atoms and pieces (lp2pieces.py) and writes the editor's
PROJECT/.preview/geo.json + geo.bin (see write_geo; positions in metres, LP2 cm / 100, Y up) and each
material's colour map (_BM) as tex/*.png. Rebuilt only when the project's stage settings change
(PROJECT/.preview/stage.key). Prints '@progress F TEXT' lines (0..1) for the editor's progress bar.
write_glb is kept for a one-file view of a stage (stage_meshes -> any glTF viewer).
"""
import argparse, hashlib, io, json, os, struct, subprocess, sys, tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2mapc, lp2pieces, lp2project, mod2obj, tex2dds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE_FMT, STRIDE = 0x49B4F022, 28


def png(rtex, max_size):
    """rTexture -> PNG bytes, or None."""
    with tempfile.TemporaryDirectory() as t:
        dds = os.path.join(t, "t.dds")
        r = subprocess.run([sys.executable, os.path.join(HERE, "tex2dds.py"), rtex, dds], capture_output=True)
        if r.returncode or not os.path.exists(dds):
            return None
        return tex2dds.dds_png(dds, max_size)


def stage_meshes(path):
    """{material: (pos, nrm, uv, col, tris)} of a static stage rModel, high LOD only."""
    b = open(path, "rb").read()
    M = mod2obj.read_model(b)
    out = {}
    for m in M["meshes"]:
        if m["fmt"] != STAGE_FMT or not (m["lodmask"] & 1) or not m["icount"]:
            continue
        idx = np.frombuffer(b, "<u2", m["icount"], M["ib"] + m["istart"] * 2).astype(np.int64)
        used, inv = np.unique(idx, return_inverse=True)
        raw = np.frombuffer(b, np.uint8, (int(used.max()) + m["vbase"] + 1) * STRIDE, M["vb"] + m["voff"])
        v = raw.reshape(-1, STRIDE)[used + m["vbase"]]
        pos = v[:, :12].copy().view("<f4").reshape(-1, 3) / 100.0
        nrm = (v[:, 12:15].astype(np.float32) - 127.0) / 127.0
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-6)
        uv = v[:, 20:24].copy().view("<f2").reshape(-1, 2).astype(np.float32)
        col = v[:, 24:28].copy()
        tris = inv.reshape(-1, 3)
        tris = tris[(tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])]
        acc = out.setdefault(m["mat"], [[], [], [], [], [], 0])
        acc[0].append(pos); acc[1].append(nrm); acc[2].append(uv); acc[3].append(col); acc[4].append(tris + acc[5])
        acc[5] += len(pos)
    res = {k: tuple(np.concatenate(a[i]) for i in range(5)) for k, a in out.items()}
    return M, res


def material_texture(M, mat):
    """The colour map name of a material (first texture slot whose name has _bm), or None."""
    for slot in M["mats"][mat]:
        if 0 < slot <= len(M["texs"]):
            n = M["texs"][slot - 1]
            if "_bm" in n.lower():
                return n
    return None


def write_glb(dst, M, meshes, tex_files, max_tex):
    bin_, views, accessors = bytearray(), [], []

    def view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), **({"target": target} if target else {})))
        bin_.extend(data)
        return len(views) - 1

    def accessor(arr, ctype, typ, normalized=False, target=34962, minmax=False):
        a = dict(bufferView=view(arr.tobytes(), target), componentType=ctype, count=len(arr), type=typ)
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accessors.append(a)
        return len(accessors) - 1

    images, textures, materials, prims, tex_index = [], [], [], [], {}
    for mat, (pos, nrm, uv, col, tris) in sorted(meshes.items()):
        tn = material_texture(M, mat)
        tex = None
        if tn and tn.lower() in tex_files:
            if tn.lower() not in tex_index:
                data = png(tex_files[tn.lower()], max_tex)
                if data:
                    images.append(dict(bufferView=view(data), mimeType="image/png", name=tn.split("\\")[-1]))
                    textures.append(dict(source=len(images) - 1, sampler=0))
                    tex_index[tn.lower()] = len(textures) - 1
            tex = tex_index.get(tn.lower())
        pbr = dict(metallicFactor=0.0, roughnessFactor=1.0)
        if tex is not None:
            pbr["baseColorTexture"] = dict(index=tex)
        materials.append(dict(name=f"mat{mat:03d}", pbrMetallicRoughness=pbr))
        attrs = dict(POSITION=accessor(pos.astype("<f4"), 5126, "VEC3", minmax=True),
                     NORMAL=accessor(nrm.astype("<f4"), 5126, "VEC3"),
                     TEXCOORD_0=accessor(uv.astype("<f4"), 5126, "VEC2"),
                     COLOR_0=accessor(col.astype(np.uint8), 5121, "VEC4", normalized=True))
        prims.append(dict(attributes=attrs, indices=accessor(tris.astype("<u4").ravel(), 5125, "SCALAR", target=34963),
                          material=len(materials) - 1))
    gltf = dict(asset=dict(version="2.0", generator="lp2preview.py"), scene=0, scenes=[dict(nodes=[0])],
                nodes=[dict(name="stage", mesh=0)], meshes=[dict(name="stage", primitives=prims)],
                materials=materials, textures=textures, images=images,
                samplers=[dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)],
                accessors=accessors, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    if not textures:
        for k in ("textures", "images", "samplers"):
            gltf.pop(k)
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    with open(dst, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_))


def slot_textures(S, raw, tex_files):
    """{texture name: bytes} of a material's texture slots (the editor costs other maps' pieces with it)"""
    out = {}
    for k in (3, 4, 5):
        t = struct.unpack_from("<I", raw, 4 * k)[0]
        if 0 < t <= len(S["textures"]) and S["textures"][t - 1].lower() in tex_files:
            out[S["textures"][t - 1].split("\\")[-1].lower()] = os.path.getsize(tex_files[S["textures"][t - 1].lower()])
    return out


def add_texture_sizes(prev):
    """older previews: add the materials' texture sizes to geo.json"""
    geo = os.path.join(prev, "geo.json")
    g = json.load(open(geo))
    if all("textures" in m for m in g["materials"]):
        return
    stage = os.path.join(prev, "stage")
    tex_files, model = {}, None
    for d, _, fs in os.walk(stage):
        for f in fs:
            if f.endswith(".rTexture"):
                rel = os.path.relpath(os.path.join(d, f[:-9]), stage).replace(os.sep, "\\").lower()
                tex_files[rel] = os.path.join(d, f)
            elif f == "online00.rModel":
                model = os.path.join(d, f)
    S = lp2pieces.read_stage(model)
    for m, raw in zip(g["materials"], S["materials"]):
        m["textures"] = slot_textures(S, raw, tex_files)
    json.dump(g, open(geo, "w"), separators=(",", ":"))


def write_geo(prev, S, per_mesh, n, tex_files, max_tex, log=print):
    """PROJECT/.preview/geo.bin + geo.json (the editor's level geometry) and tex/*.png.
    Vertices and triangles are sorted into blocks by (atom, material); a block's indices are local to it.
    geo.bin: pos f32 x3 (m), nrm f32 x3, uv f32 x2, col f32 x4 (baked light 0..1), idx i32."""
    nmat = len(S["materials"])
    P, N, U, C, VK, T, TK = [], [], [], [], [], [], []
    base = 0
    for m, ta in zip(S["meshes"], per_mesh):
        v = m["v"]
        va = np.zeros(len(v), np.int64)
        va[m["tris"]] = ta[:, None]
        P.append(v[:, :12].copy().view("<f4").reshape(-1, 3) / 100.0)
        nr = (v[:, 12:15].astype(np.float32) - 127.0) / 127.0
        N.append(nr / np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-6))
        U.append(v[:, 20:24].copy().view("<f2").reshape(-1, 2).astype(np.float32))
        C.append(v[:, 24:28].astype(np.float32) / 255.0)
        VK.append(va * nmat + m["mat"])
        T.append(m["tris"] + base)
        TK.append(ta * nmat + m["mat"])
        base += len(v)
    P, N, U, C, VK, T, TK = map(np.concatenate, (P, N, U, C, VK, T, TK))
    vo = np.argsort(VK, kind="stable")
    newid = np.empty(len(vo), np.int64)
    newid[vo] = np.arange(len(vo))
    to = np.argsort(TK, kind="stable")
    T, TK, VK = newid[T[to]], TK[to], VK[vo]
    keys, v0, vn = np.unique(VK, return_index=True, return_counts=True)
    tkeys, i0, tc = np.unique(TK, return_index=True, return_counts=True)
    assert (keys == tkeys).all()
    T = T - np.repeat(v0, tc)[:, None]  # block-local
    arrays, bin_ = {}, bytearray()
    for name, arr in (("pos", P[vo]), ("nrm", N[vo]), ("uv", U[vo]), ("col", C[vo]), ("idx", T.ravel())):
        data = arr.astype("<i4" if name == "idx" else "<f4").tobytes()
        arrays[name] = [len(bin_), len(data)]
        bin_ += data
    open(os.path.join(prev, "geo.bin"), "wb").write(bin_)
    tdir = os.path.join(prev, "tex")
    os.makedirs(tdir, exist_ok=True)
    mats, tex_bytes = [], 0
    for k, raw in enumerate(S["materials"]):
        print(f"@progress {0.75 + 0.2 * (k + 1) / nmat:.3f} preview textures", flush=True)
        slot = struct.unpack_from("<I", raw, 12)[0]
        tn = S["textures"][slot - 1] if 0 < slot <= len(S["textures"]) else None
        png_rel = None
        if tn and tn.lower() in tex_files:
            png_rel = "tex/" + tn.split("\\")[-1] + ".png"
            if not os.path.exists(os.path.join(prev, png_rel)):
                data = png(tex_files[tn.lower()], max_tex)
                if data:
                    open(os.path.join(prev, png_rel), "wb").write(data)
                else:
                    png_rel = None
        mats.append(dict(tex=png_rel, name=tn.split("\\")[-1] if tn else None, textures=slot_textures(S, raw, tex_files)))
    tex_bytes = sum(os.path.getsize(f) for f in tex_files.values())
    tree = lp2pieces.default_tree(S, per_mesh, n)
    blocks = np.stack([keys // nmat, keys % nmat, v0, vn, i0 * 3, tc * 3], 1).tolist()
    stats = dict(atoms=n, vertices=int(len(P)), triangles=int(len(T)), materials=nmat, textures=len(tex_files),
                 texture_bytes=tex_bytes)
    lo, hi, _ = lp2pieces.atom_boxes(S, per_mesh, n)
    boxes = np.round(np.concatenate([lo, hi], 1) / 100.0, 4).ravel().tolist()  # per atom: min xyz, max xyz (m)
    json.dump(dict(version=1, arrays=arrays, materials=mats, blocks=blocks, atom_box=boxes, tree=tree, stats=stats),
              open(os.path.join(prev, "geo.json"), "w"), separators=(",", ":"))
    return stats


def stock_budget(stock_scr):
    """Bytes of the stock map's stage resources (scr arc models and textures): the memory target."""
    total = {}
    for cls in ("rModel", "rTexture", "rCollision"):
        total[cls] = sum(len(d) for _, d in stock_scr.get(cls, []))
    return total


def build(game, folder, max_tex=1024, log=print):
    p = lp2project.load(folder)
    prev = os.path.join(folder, ".preview")
    os.makedirs(prev, exist_ok=True)
    key = hashlib.sha1(json.dumps([p["stage"], max_tex, "geo3"], sort_keys=True).encode()).hexdigest()
    geo, keyf = os.path.join(prev, "geo.json"), os.path.join(prev, "stage.key")
    if os.path.exists(geo) and os.path.exists(keyf) and open(keyf).read() == key:
        add_texture_sizes(prev)
        log(f"{geo}: up to date")
        return geo
    print("@progress 0.0 stock map", flush=True)
    stock = lp2mapc.entries(os.path.join(game, "nativePC", lp2mapc.ARCS["scr"]))
    tmpl = os.path.join(prev, "online00.rModel")
    open(tmpl, "wb").write(next(d for n, d in stock["rModel"] if lp2mapc.base(n).lower() == "online00"))
    stage = os.path.join(prev, "stage")
    log("stage model (lp2stage.py)")
    lp2mapc.tool("lp2stage.py", "--template", tmpl, "--out", stage, "--tex-dir", lp2mapc.STAGE_DIR,
                 "--light", p["stage"].get("light_scale", 0.5), "--balance", p["stage"].get("light_balance", 1.0),
                 *[lp2project.path(folder, m) for m in p["stage"]["lp1_models"]], progress=(0.02, 0.6))
    model = os.path.join(stage, *lp2mapc.STAGE_DIR.split("\\"), "online00.rModel")
    tex_files = {}
    for d, _, fs in os.walk(stage):
        for f in fs:
            if f.endswith(".rTexture"):
                rel = os.path.relpath(os.path.join(d, f[:-9]), stage).replace(os.sep, "\\").lower()
                tex_files[rel] = os.path.join(d, f)
    print("@progress 0.62 splitting into pieces", flush=True)
    S = lp2pieces.read_stage(model)
    per_mesh, n = lp2pieces.atoms(S)
    print("@progress 0.7 piece tree", flush=True)
    stats = write_geo(prev, S, per_mesh, n, tex_files, max_tex, log)
    os.path.exists(os.path.join(prev, "stage.glb")) and os.remove(os.path.join(prev, "stage.glb"))  # the old preview
    stats["model_bytes"] = os.path.getsize(model)
    stats["stock"] = stock_budget(stock)
    g = json.load(open(geo))
    g["stats"] = stats
    json.dump(g, open(geo, "w"), separators=(",", ":"))
    open(keyf, "w").write(key)
    print("@progress 1.0 done", flush=True)
    log(f"geometry: {stats['vertices']} vertices, {stats['triangles']} triangles, {n} atoms, {len(g['tree'])} pieces, "
        f"{stats['materials']} materials")
    return geo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--max-tex", type=int, default=1024)
    ap.add_argument("project")
    a = ap.parse_args()
    build(a.game, a.project, a.max_tex)


if __name__ == "__main__":
    main()
