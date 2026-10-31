#!/usr/bin/env python3
"""The map editor's asset library: game models as GLB (metres, Y-up, PNG textures), with an index.

  lp2library.py get --game LP2_DIR [--lp1 LP1_DIR] [--lp1-360 NATIVEXENON] [--force] LIB

LP2: every VS type, fixed weapon and data post (build_marker_assets.py: uVs/uWp/uOm archives -> OBJ + DDS,
kept under LIB/raw/lp2 and reused unless --force), then each model's top LOD (meshes with UVs) as
LIB/lp2/<key>.glb with its colour maps (at most 256 px; models whose vertex format
hides the UVs come out grey).
LIB/index.json: {"assets": [{key, name, source "LP2", group "Vehicles" | "Weapons" | "Objects", glb, size [x, y, z] m}]}.
Keys are the marker keys (vs_50, wp_05, om_7100).
LP1: every map archive (ZZPack2/s8xx, s9xx) from the PC install, and the ones only the 360 Colonies disc has
(xiso.py's nativeXenon tree) -> a small project LIB/lp1/<sid> (lp2project import) with its editor preview
(.preview: geo.json / geo.bin / 256 px textures, lp2preview.py), so the editor can show the map's pieces.
Index entry: {key "lp1_s900", name, source "LP1", group "Maps", map "lp1/s900", from "PC" | "360"}.
LP2 objects: every uOm model as one props map LIB/lp2/props (lp2props.py; built once, again with --force),
index entry {key "lp2_props", name "LP2 objects", group "Props", map "lp2/props"}.
LP2 maps: every stock online map's stage pieces and collision as a map LIB/lp2/mapNN (lp2stockmaps.py; each built
once, again with --force), index entry {key "lp2_mapNN", name "LP2 map Desecration", group "Maps", map "lp2/mapNN"}. Progress lines: @progress F TEXT (lp2mapc / the editor).
Nothing from the games is shipped: the library is made from the user's own installs.
"""
import argparse, json, os, re, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_marker_assets, lp2props, lp2stockmaps, tex2dds  # noqa: E402

TEX_MAX = 256
GLB_VERSION = 2   # LIB/lp2/glb_version: older GLBs are rebuilt from the kept raw models (2: normals, brightness)
# LP2's VS / weapon colour maps are dark (VS 00: mean 28 / 255): the game's shader lifts them (specular, reflections),
# the editor's plain material doesn't, so each model's maps are brightened together: towards BRIGHT_MEAN on average,
# its 95th percentile at most to BRIGHT_TOP (the few brighter ones clip), by at most BRIGHT_MAX
BRIGHT_MEAN, BRIGHT_TOP, BRIGHT_MAX = 110.0, 240.0, 4.0


def progress(f, text=""):
    print(f"@progress {f:.3f} {text}", flush=True)


def png(path, max_size=TEX_MAX):
    return tex2dds.dds_png(path, max_size)


def brightened(paths):
    """colour map paths -> {path: PNG bytes}, all lifted by one gain (see BRIGHT_MEAN)"""
    import io
    import numpy as np
    from PIL import Image
    ims = {}
    for p in paths:
        data = png(p)
        if data:
            ims[p] = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"), np.float32)
    if not ims:
        return {}
    rgb = np.concatenate([a[..., :3].reshape(-1, 3) for a in ims.values()])
    mean, top = float(rgb.mean()), float(np.percentile(rgb, 95))
    gain = max(1.0, min(BRIGHT_MEAN / max(mean, 1.0), BRIGHT_TOP / max(top, 1.0), BRIGHT_MAX))
    out = {}
    for p, a in ims.items():
        a = a.copy()
        a[..., :3] = np.clip(a[..., :3] * gain, 0, 255)
        b = io.BytesIO()
        Image.fromarray(a.astype(np.uint8), "RGBA").save(b, "PNG")
        out[p] = b.getvalue()
    return out


def read_obj(path):
    """top-LOD meshes with UVs, grouped by material: {mat: (positions, uvs, triangles)} in metres, and the MTL's colour maps."""
    v, vt, out, plain, mats = [], [], {}, {}, {}
    keep, mat = False, None
    d = os.path.dirname(path)
    for line in open(path):
        k = line[:2]
        if k == "v ":
            x, y, z = line.split()[1:4]
            v.append((float(x) * 0.01, float(y) * 0.01, float(z) * 0.01))
        elif k == "vt":
            u, w = line.split()[1:3]
            vt.append((float(u), 1.0 - float(w)))   # OBJ: V up; glTF: V down
        elif k == "o ":
            m = re.search(r"_lod([0-9a-f]{2})_", line)
            keep = m is None or int(m.group(1), 16) & 1
        elif line.startswith("usemtl"):
            mat = line.split()[1]
        elif k == "f " and keep:
            corners = [c.split("/") for c in line.split()[1:]]
            has_uv = all(len(c) > 1 and c[1] for c in corners)   # no UVs: shadow / collision, or an unknown format
            P, U, T, seen = (out if has_uv else plain).setdefault(mat if has_uv else "_plain", ([], [], [], {}))
            idx = []
            for c in corners:
                ck = (c[0], c[1] if has_uv else "")
                if ck not in seen:   # shared corners: one vertex
                    seen[ck] = len(P)
                    P.append(v[int(c[0]) - 1])
                    U.append(vt[int(c[1]) - 1] if has_uv else (0.0, 0.0))
                idx.append(seen[ck])
            for i in range(1, len(idx) - 1):
                T.append((idx[0], idx[i], idx[i + 1]))
    mtl = os.path.splitext(path)[0] + ".mtl"
    cur = None
    if os.path.exists(mtl):
        for line in open(mtl):
            if line.startswith("newmtl"):
                cur = line.split()[1]
            elif line.startswith("map_Kd") and cur:
                p = os.path.join(d, line.split(None, 1)[1].strip())
                if os.path.exists(p):
                    mats[cur] = p
    return out or plain, mats


def normals(P, T):
    """-> P, T, N with smooth normals; a vertex shared by faces facing opposite ways (both sides of a plate: their
    normals cancelled out, so the model looked black) is split, each side keeping its own normal. P, T: index lists
    (the extra vertices copy their original: the callers' other per-vertex lists use remap)"""
    import numpy as np
    Pa, Ta = np.asarray(P, np.float64), np.asarray(T, np.int64).reshape(-1, 3)
    fn = np.cross(Pa[Ta[:, 1]] - Pa[Ta[:, 0]], Pa[Ta[:, 2]] - Pa[Ta[:, 0]])          # area weighted
    area = np.linalg.norm(fn, axis=1)
    keep = area > 1e-10                                     # no flat faces (some models' shadow shells are all flat)
    Ta, fn, area = Ta[keep], fn[keep], area[keep]
    # each vertex's reference: its largest face; corners facing against it go to a copy
    ref = np.zeros((len(Pa), 3))
    order = np.argsort(area)                                                      # largest written last
    for k in range(3):
        ref[Ta[order, k]] = fn[order]
    flip = np.einsum("ij,ij->i", fn[:, None, :].repeat(3, 1).reshape(-1, 3), ref[Ta.ravel()]).reshape(-1, 3) < 0
    T2 = Ta + flip * len(Pa)
    N = np.zeros((2 * len(Pa), 3))
    for k in range(3):
        np.add.at(N, T2[:, k], fn)
    used = np.unique(T2)
    remap = np.full(2 * len(Pa), -1, np.int64)
    remap[used] = np.arange(len(used))
    N = N[used]
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    src = used % len(Pa)                                                          # the original of each vertex
    return src.tolist(), remap[T2].tolist(), N.tolist()


def write_glb(dst, meshes, tex):
    """one mesh, a primitive per material (double-sided, colour map embedded)."""
    bin_, views, acc, prims, materials, images, textures = bytearray(), [], [], [], [], [], []

    def view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), **({"target": target} if target else {})))
        bin_.extend(data)
        return len(views) - 1

    lo, hi = [1e9] * 3, [-1e9] * 3
    lifted = brightened(sorted({tex[m] for m in meshes if m in tex}))
    for mat, (P, U, T, _seen) in meshes.items():
        if not T:
            continue
        src, T, N = normals(P, T)
        if not T:
            continue
        P, U = [P[i] for i in src], [U[i] for i in src]
        pmin = [min(p[i] for p in P) for i in range(3)]
        pmax = [max(p[i] for p in P) for i in range(3)]
        lo = [min(lo[i], pmin[i]) for i in range(3)]
        hi = [max(hi[i], pmax[i]) for i in range(3)]
        a = len(acc)
        acc.append(dict(bufferView=view(struct.pack(f"<{3 * len(P)}f", *[c for p in P for c in p]), 34962), componentType=5126,
                        count=len(P), type="VEC3", min=pmin, max=pmax))
        acc.append(dict(bufferView=view(struct.pack(f"<{3 * len(N)}f", *[c for n in N for c in n]), 34962), componentType=5126,
                        count=len(N), type="VEC3"))
        acc.append(dict(bufferView=view(struct.pack(f"<{2 * len(U)}f", *[c for u in U for c in u]), 34962), componentType=5126,
                        count=len(U), type="VEC2"))
        acc.append(dict(bufferView=view(struct.pack(f"<{3 * len(T)}I", *[i for t in T for i in t]), 34963), componentType=5125,
                        count=3 * len(T), type="SCALAR"))
        m = dict(name=mat, doubleSided=True, pbrMetallicRoughness=dict(metallicFactor=0.0, roughnessFactor=1.0))
        data = lifted.get(tex[mat]) if mat in tex else None
        if data:
            images.append(dict(bufferView=view(data), mimeType="image/png"))
            textures.append(dict(source=len(images) - 1))
            m["pbrMetallicRoughness"]["baseColorTexture"] = dict(index=len(textures) - 1)
        else:
            m["pbrMetallicRoughness"]["baseColorFactor"] = [0.6, 0.6, 0.6, 1.0]
        materials.append(m)
        prims.append(dict(attributes=dict(POSITION=a, NORMAL=a + 1, TEXCOORD_0=a + 2), indices=a + 3, material=len(materials) - 1))
    if not prims:
        return None
    while len(bin_) % 4:
        bin_.append(0)
    gltf = dict(asset=dict(version="2.0", generator="lp2library"), scene=0, scenes=[dict(nodes=[0])],
                nodes=[dict(mesh=0, name=os.path.splitext(os.path.basename(dst))[0])], meshes=[dict(primitives=prims)],
                accessors=acc, bufferViews=views, buffers=[dict(byteLength=len(bin_))], materials=materials)
    if images:
        gltf["images"], gltf["textures"] = images, textures
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    with open(dst, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(bin_), 0x004E4942) + bin_)
    return [round(hi[i] - lo[i], 2) for i in range(3)]


def lp2_names():
    A = build_marker_assets.tables()
    names = {}
    for tid, model, _size, flying in A.VS_TYPES:
        names[f"vs_{tid:02x}"] = ("Vehicles", f"VS {tid:02X} ({model}{', flying' if flying else ''})")
    defaults = {0x30: "Assault Rifle", 0x31: "Shotgun", 0x32: "Rifle", 0x33: "Rocket Launcher", 0x34: "Shield", 0x0c: "Handgun",
                0x15: "Frag Grenade", 0x16: "Gum Grenade", 0x17: "Disk Grenade", 0x18: "Dummy Grenade",
                0x19: "Plasma Grenade"}   # a slot's default (variant 00) weapon
    for w in sorted({w for w, _ in A.PICKUPS} | set(A.VS_WEAPONS)):
        names[f"wp_{w:02x}"] = ("Weapons", defaults.get(w) or f"Weapon {w:02X}" + (" (VS mount)" if w in A.VS_WEAPONS else ""))
    for _item, model, title in A.POSTS:
        names[f"om_{model[2:]}"] = ("Objects", title)
    return names


def lp1_arcs(a):
    """{sid: (arc path, "PC" | "360")}: PC first, then what only the 360 disc has."""
    out = {}
    for root, src in ((a.lp1_360, "360"), (a.lp1, "PC")):   # PC last: it wins
        if not root:
            continue
        for sub in ("nativePC", "nativeXenon", ""):
            d = os.path.join(root, sub, "ZZPack2")
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if re.fullmatch(r"s\d{3}\.arc", f.lower()):
                        out[f[:-4].lower()] = (os.path.join(d, f), src)
                break
    return out


def lp1_maps(a, lib):
    import lp2mapc, lp2project
    arcs = lp1_arcs(a)
    out = []
    for i, (sid, (arc, src)) in enumerate(sorted(arcs.items())):
        lo, hi = 0.0 + i / len(arcs), (i + 1) / len(arcs)
        folder = os.path.join(lib, "lp1", sid)
        if a.force or not os.path.exists(os.path.join(folder, "project.json")):
            progress(lo, f"Importing LP1 {sid} ({src})")
            empty = os.path.join(lib, "lp1", "empty-layout.json")   # pieces only (PC layouts: lp1points.py can't read them yet)
            os.makedirs(os.path.dirname(empty), exist_ok=True)
            json.dump(dict(sets=[]), open(empty, "w"))
            try:
                lp2project.import_lp1(arc, folder, f"LP1 {sid}", layout=empty)
            except SystemExit as e:
                print(f"lp1 {sid}: skipped ({e})")
                continue
        try:
            lp2mapc.tool("lp2preview.py", "--game", a.game, "--max-tex", 256, folder, progress=(lo, hi))
        except SystemExit as e:
            print(f"lp1 {sid}: no preview ({str(e).splitlines()[0]})")
            continue
        out.append(dict(key=f"lp1_{sid}", name=f"LP1 {sid}", source="LP1", group="Maps", map=f"lp1/{sid}", **{"from": src}))
        print(f"lp1 {sid}: {src}")
    return out


def get(a):
    lib = os.path.abspath(a.lib)
    raw = os.path.join(lib, "raw", "lp2")
    have = os.path.join(raw, "manifest.json")
    none = os.path.join(raw, "no_model.json")   # keys the game has no model for: not ripped again
    skip = set(json.load(open(none))) if os.path.exists(none) and not a.force else set()
    missing = [] if a.force or not os.path.exists(have) else \
        sorted(set(lp2_names()) - set(json.load(open(have))) - skip)
    if a.force or not os.path.exists(have) or missing:
        # a library from an older version: rip only the models it lacks (build_marker_assets.py KEY ...)
        progress(0.0, "Ripping LP2 models (VS, weapons, posts)")
        r = subprocess.run([sys.executable, os.path.join(HERE, "build_marker_assets.py"), a.game, raw] + missing)
        if r.returncode:
            raise SystemExit("build_marker_assets.py failed")
        json.dump(sorted(skip | (set(lp2_names()) - set(json.load(open(have))))), open(none, "w"))
    manifest = json.load(open(os.path.join(raw, "manifest.json")))
    names = lp2_names()
    os.makedirs(os.path.join(lib, "lp2"), exist_ok=True)
    assets = []
    keys = sorted(manifest)
    ver = os.path.join(lib, "lp2", "glb_version")
    stale = not os.path.exists(ver) or open(ver).read().strip() != str(GLB_VERSION)
    for i, key in enumerate(keys):
        progress(0.5 + 0.5 * i / len(keys), f"Converting {key}")
        dst = os.path.join(lib, "lp2", key + ".glb")
        if a.force or stale or not os.path.exists(dst):
            meshes, tex = read_obj(os.path.join(raw, manifest[key]))
            size = write_glb(dst, meshes, tex)
        else:
            size = None
        if not os.path.exists(dst):
            print(f"{key}: no textured mesh, skipped")
            continue
        group, name = names.get(key, ("Objects", key))
        e = dict(key=key, name=name, source="LP2", group=group, glb=os.path.relpath(dst, lib))
        if size:
            e["size"] = size
        assets.append(e)
    open(ver, "w").write(str(GLB_VERSION))
    if a.lp1 or a.lp1_360:
        assets += lp1_maps(a, lib)
    if a.force or not os.path.exists(os.path.join(lib, *lp2props.REL.split("/"), "project.json")):
        progress(0.0, "LP2 objects (props)")
        assets.append(lp2props.build(a.game, lib))
    nums = lp2stockmaps.numbers(a.game)
    for i, num in enumerate(nums):   # LP2's own maps' pieces
        if a.force or not os.path.exists(os.path.join(lib, *lp2stockmaps.rel(num).split("/"), "project.json")):
            try:
                lp2stockmaps.build(a.game, lib, num, span=(i / len(nums), (i + 1) / len(nums)))
            except SystemExit as e:
                print(f"lp2 map {num}: skipped ({e})")
                continue
        if os.path.exists(os.path.join(lib, *lp2stockmaps.rel(num).split("/"), "project.json")):
            assets.append(lp2stockmaps.entry(num))
    old = {}
    idx = os.path.join(lib, "index.json")
    if os.path.exists(idx):   # keep sizes measured by an earlier run
        old = {e["key"]: e for e in json.load(open(idx)).get("assets", [])}
    if not (a.lp1 or a.lp1_360):  # LP1 maps not asked for this run: keep the ones already built
        assets += [e for e in old.values() if "map" in e and e["key"].startswith("lp1_") and os.path.isdir(os.path.join(lib, e["map"]))]
    have = {e["key"] for e in assets}
    if os.path.exists(os.path.join(lib, *lp2props.REL.split("/"), "project.json")) and "lp2_props" not in have:
        assets.append(dict(key="lp2_props", name="LP2 objects", source="LP2", group="Props", map=lp2props.REL))
    for e in assets:
        if "size" not in e and "size" in old.get(e["key"], {}):
            e["size"] = old[e["key"]]["size"]
    json.dump(dict(assets=assets), open(idx, "w"), indent=1)
    progress(1.0, "Done")
    print(f"{len(assets)} assets -> {lib}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("--game", required=True)
    g.add_argument("--lp1", help="Lost Planet 1 (Steam) folder")
    g.add_argument("--lp1-360", help="the Colonies disc's nativeXenon tree (xiso.py)")
    g.add_argument("--force", action="store_true")
    g.add_argument("lib")
    a = ap.parse_args()
    get(a)


if __name__ == "__main__":
    main()
