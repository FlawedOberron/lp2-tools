#!/usr/bin/env python3
"""Port a Lost Planet 1 multiplayer map to Lost Planet 2: one LP1 stage archive -> one Maps\\*.zip package.

  lp1map.py --game LP2_DIR --lp1 sNNN.arc --name "Area 921" OUT.zip [options]

--lp1: the Xbox 360 (Colonies) ZZPack2/sNNN.arc; every stage model, collision, physics and layout comes
from it. The package is stock online map 00 (Desecration) with everything map-specific swapped:
  stage model + textures   lp2stage.py (LP1 lightmaps baked into vertex colour)
  collision                lp2col.py (atari = movement, tama = bullets)
  physics (grenades...)    lp2havok.py
  spawns, VS, weapons      lp1points.py + lp2layout.py --lp1-vs, or --layout (Blender LP2 Map Markers export)
  light, sky, intro camera lp2light.py (static daylight; --sun etc.; no weather or water; written to both
                           the main and variable arcs, whose copies the game uses); Desecration water planes stubbed
  occluders                emptied (map 00's would cull the new geometry)
  resource paths           arcsub.py 'scr\\Online\\online00\\' -> 'scr\\Online\\<tag>\\' so the game's
                           path-keyed cache never mixes it up with Desecration or another ported map
Every file comes from the user's own game install and LP1 archive; the zip is for personal use / sharing
between players who own both games, like any Maps package.

Options:
  --tag NAME      8-character resource folder (default lp1sNNN_); must differ between packages
  --size S        small / medium / large: the lobby's size class (default large)
  --layout JSON   authored layout (blender_lp2_map_markers.py "Export Layout") instead of LP1's own
  --sun X,Y,Z     direction towards the sun (default 0.472,0.848,0.241); --tint R,G,B the sun colour
  --sky / --bloom / --curves   lp2light.py filter overrides (defaults: Battlegrounds' neutral daylight)
  --thumb IMAGE   create-match thumbnail (lp2thumb.py; --zoom, --at)
  --exclude TEXT  skip LP1 stage models whose name contains TEXT (repeatable; e.g. _sky)
  --work DIR      keep the intermediate files there (default: a temporary folder)
"""
import argparse, json, math, os, shutil, struct, subprocess, sys, tempfile, zipfile, zlib
import numpy as np
import arcx, mapslot, sbc

HERE = os.path.dirname(os.path.abspath(__file__))
STOCK = 0
ARCS = {"main": "arcXmlTmpPC/aArea_ONLINE_00.arc", "v": "arcXmlTmpPC/variable/aArea_ONLINE_00_v.arc",
        "auto": "arcLp2Xml/autoArc/aArea_ONLINE_00.arc", "scr": "arcLp2Xml/autoArc/aArea_ONLINE_00_scr.arc"}
STAGE_DIR = "scr\\Online\\online00"
STUBS = ["online00_car1", "online00_car2", "online00_car3", "online00_car4", "online00_shadow"]
LIGHT = dict(sun="0.472,0.848,0.241", tint="0.93,0.97,1.1", sky="8.5,9.2,10", bloom="0.42,0.45,0.5",
             curves="R:0,0.215,0.69,0.97;G:0,0.222,0.70,0.985;B:0,0.227,0.711,1")


def tool(name, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, name), *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"{name} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


def entries(arc):
    """{class: [(full name, data)]} of an archive."""
    d, types, out = open(arc, "rb").read(), arcx.load_types(), {}
    for n, h, cs, ds, fl, o in arcx.entries(d):
        out.setdefault(types.get(h), []).append((n, zlib.decompress(d[o:o + cs]) if cs != ds else d[o:o + cs]))
    return out


def base(name):
    return name.split("\\")[-1]


def put(arc, files):
    """arcput.py in place: files = {NAME.CLASS: path}."""
    if files:
        tool("arcput.py", arc, arc + ".new", *(f"{k}={v}" for k, v in files.items()))
        os.replace(arc + ".new", arc)


def stock_package(game, pkg):
    native = os.path.join(game, "nativePC")
    for rel in mapslot.map_files(native, STOCK):
        s = os.path.join(native, rel)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(pkg, "nativePC", rel))
        elif os.path.exists(s):
            os.makedirs(os.path.dirname(os.path.join(pkg, "nativePC", rel)), exist_ok=True)
            shutil.copyfile(s, os.path.join(pkg, "nativePC", rel))
    for arc, name, cls, ext in mapslot.BOOT_RESOURCES:  # per-map resources the game also reads loose
        n = name.format(STOCK)
        data = next(d for x, d in entries(os.path.join(native, arc))[cls] if x.lower() == n.lower())
        out = os.path.join(pkg, "nativePC", *n.split("\\")) + "." + ext
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(data)


def lp1_files(arc, out):
    """LP1 stage models, collision and physics, as <name>.<type hash>."""
    d, got = open(arc, "rb").read(), {}
    for n, h, cs, ds, fl, o in arcx.entries(d):
        if n.lower().startswith(("scr\\", "havokdata\\")):
            p = os.path.join(out, *n.lower().split("\\")) + f".{h:#010x}"
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(zlib.decompress(d[o:o + cs]) if cs != ds else d[o:o + cs])
            got.setdefault(h, []).append(p)
    return got


def build_scr(stock_scr, stage_out, dst):
    """The stock _scr archive with Desecration's stage textures dropped and ours added."""
    lt = arcx.load_types()
    order, have = [], set()
    ent = entries(stock_scr)
    for cls, items in ent.items():
        for n, data in items:
            if cls == "rTexture" and n.lower().startswith(STAGE_DIR.lower() + "\\") and not n.lower().endswith("_cm-01"):
                continue
            p = os.path.join(stage_out, *n.split("\\")) + "." + cls
            if not os.path.exists(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "wb").write(data)
    for n, h, *_ in arcx.entries(open(stock_scr, "rb").read()):
        if os.path.exists(os.path.join(stage_out, *n.split("\\")) + "." + lt[h]):
            order.append((n, lt[h])); have.add(n.lower())
    for d, _, fs in os.walk(stage_out):
        for f in sorted(fs):
            stem, _, cls = f.rpartition(".")
            n = os.path.relpath(os.path.join(d, stem), stage_out).replace(os.sep, "\\")
            if cls in ("rTexture", "rModel") and n.lower() not in have:
                order.append((n, cls)); have.add(n.lower())
    open(os.path.join(stage_out, ".arcorder"), "w", encoding="latin-1").write("".join(f"{n}\t{c}\n" for n, c in order))
    arcx.pack(stage_out, dst)


class Floor:
    """Vertical rays against the movement collision."""
    def __init__(self, path):
        c = sbc.read(open(path, "rb").read())
        V, T = np.array(c["verts"]), []
        for g in c["groups"]:
            for t in c["tris"][g["tri"]:g["tri_end"]]:
                T.append([g["vert"] + t[3], g["vert"] + t[4], g["vert"] + t[5]])
        T = np.array(T)
        self.A, self.B, self.C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        self.lo, self.hi = V.min(0), V.max(0)

    def heights(self, x, z):
        A, B, C = self.A, self.B, self.C
        d = (B[:, 2] - C[:, 2]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 2] - C[:, 2])
        ok = np.abs(d) > 1e-9; d = np.where(ok, d, 1)
        l1 = ((B[:, 2] - C[:, 2]) * (x - C[:, 0]) + (C[:, 0] - B[:, 0]) * (z - C[:, 2])) / d
        l2 = ((C[:, 2] - A[:, 2]) * (x - C[:, 0]) + (A[:, 0] - C[:, 0]) * (z - C[:, 2])) / d
        l3 = 1 - l1 - l2; m = ok & (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        return np.sort(l1[m] * A[m, 1] + l2[m] * B[m, 1] + l3[m] * C[m, 1])


def lift(layout, floor):
    """LP1 markers often sit a little under the floor surface: put them 5 cm above it (up to 60 cm)."""
    n = bad = 0
    for s in layout["sets"]:
        for r in s["points"] + s["objects"]:
            x, y, z = r["pos"]; h = floor.heights(x, z)
            up = h[(h > y) & (h <= y + 60)]
            if len(up):
                r["pos"][1] = float(up.max()) + 5; n += 1
            elif not len(h[h <= y + 1]):
                bad += 1
    return n, bad


def camera(floor):
    """Intro camera: a high arc round the middle of the map, looking at the ground there."""
    cx, cz = (floor.lo[0] + floor.hi[0]) / 2, (floor.lo[2] + floor.hi[2]) / 2
    h = floor.heights(cx, cz)
    gy = float(h.max()) if len(h) else float(floor.lo[1])
    r = max(floor.hi[0] - floor.lo[0], floor.hi[2] - floor.lo[2]) * 0.4
    y = float(floor.hi[1]) + 1000
    cam = [[cx + r * math.cos(math.radians(a)), y, cz + r * math.sin(math.radians(a))] for a in (200, 215, 235, 250)]
    return dict(cam=cam, tgt=[[cx, gy, cz]] * 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--lp1", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--tag")
    ap.add_argument("--size", default="large", choices=("small", "medium", "large"))
    ap.add_argument("--layout")
    for k, v in LIGHT.items():
        ap.add_argument("--" + k, default=v)
    ap.add_argument("--thumb")
    ap.add_argument("--zoom", default="1")
    ap.add_argument("--at", default="0.5,0.5")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--work")
    ap.add_argument("out")
    a = ap.parse_args()
    sid = os.path.basename(a.lp1).split(".")[0].lower()
    tag = a.tag or ("lp1" + sid).ljust(8, "_")
    if len(tag) != 8:
        raise SystemExit("--tag must be 8 characters (it replaces 'online00')")
    work = a.work or tempfile.mkdtemp(prefix="lp1map")
    os.makedirs(work, exist_ok=True)
    pkg = os.path.join(work, "pkg")
    shutil.rmtree(pkg, ignore_errors=True)
    W = lambda *p: os.path.join(work, *p)
    try:
        print("stock map 00 ->", pkg)
        stock_package(a.game, pkg)
        A = {k: os.path.join(pkg, "nativePC", v) for k, v in ARCS.items()}
        stock = {k: entries(v) for k, v in A.items()}
        tmpl = {}
        for k, cls, name in (("scr", "rModel", "online00"), ("scr", "rCollision", "atarionline00"),
                             ("scr", "rCollision", "tamaonline00"), ("v", "rHkCollision", "havonline00")):
            tmpl[name] = W("tmpl", name + "." + cls)
            os.makedirs(W("tmpl"), exist_ok=True)
            open(tmpl[name], "wb").write(next(d for n, d in stock[k][cls] if base(n).lower() == name))

        print("LP1", sid)
        src = lp1_files(a.lp1, W("lp1"))
        models = sorted(p for p in src.get(0x1041bd9e, []) if not any(x in os.path.basename(p) for x in a.exclude))
        col = {os.path.basename(p).split(".")[0][:4]: p for p in src.get(0x3900dad0, [])}  # atari / tama
        hav = next(iter(src.get(0x3c3d0c05, [])), None)
        if not models or set(col) != {"atar", "tama"} or not hav:
            raise SystemExit(f"{a.lp1}: expected stage models, atari + tama collision and havok data")

        print("stage model:", ", ".join(os.path.basename(p).split(".")[0] for p in models))
        stage = W("stage")
        shutil.rmtree(stage, ignore_errors=True)
        tool("lp2stage.py", "--template", tmpl["online00"], "--out", stage, "--tex-dir", STAGE_DIR, "--light", "0.5",
             *sum((["--empty", s] for s in STUBS), []), *models)
        build_scr(A["scr"], stage, A["scr"])
        # Desecration's water planes (effect models, its spots only) -> the stub; water is a map setting
        stub = os.path.join(stage, STUBS[-1] + ".rModel")
        put(A["main"], {"\\o00water.rModel": stub, "\\o00water2.rModel": stub})

        for k, arc in A.items():  # own resource paths
            tool("arcsub.py", arc, arc + ".new", r"scr\\online\\online00\\", "scr\\\\Online\\\\%s\\\\" % tag)
            os.replace(arc + ".new", arc)

        print("collision + physics")
        files = {}
        for k, n in (("atar", "atarionline00"), ("tama", "tamaonline00")):
            out = W(n + ".rCollision")
            print(" ", tool("lp2col.py", col[k], tmpl[n], out).strip().split(": ", 1)[1])
            files[f"{tag}\\{n}.rCollision"] = out
        print(" ", tool("lp2havok.py", hav, tmpl["havonline00"], W("hav.rHkCollision")).strip().split(": ", 1)[1])
        put(A["scr"], files)
        put(A["v"], {**files, "havokdata\\havonline00.rHkCollision": W("hav.rHkCollision")})
        occ = next(d for n, d in stock["main"]["rOccluder"])
        occ = bytearray(occ); struct.pack_into("<I", occ, 8, 0)
        open(W("occ.rOccluder"), "wb").write(occ)
        put(A["main"], {"aArea_ONLINE_00_occ.rOccluder": W("occ.rOccluder")})

        print("layout")
        floor = Floor(W("atarionline00.rCollision"))
        if a.layout:
            layout, flags = json.load(open(a.layout)), []
        else:
            tool("lp1points.py", a.lp1, W("points.json"))
            layout, flags = json.load(open(W("points.json"))), ["--lp1-vs"]
        n, bad = lift(layout, floor)
        print(f"  {n} markers moved onto the floor, {bad} with no floor below")
        json.dump(layout, open(W("layout.json"), "w"), indent=1)
        ip_in, ip_out = W("ip", "in"), W("ip", "out")
        shutil.rmtree(W("ip"), ignore_errors=True); os.makedirs(ip_in)
        for k in ("main", "v"):
            for cls, ext in (("rInitPosSet", "xfs"), ("rObjSet", "osf")):
                for nm, data in stock[k].get(cls, []):
                    open(os.path.join(ip_in, base(nm) + "." + ext), "wb").write(data)
        tool("lp2layout.py", *flags, W("layout.json"), ip_in, ip_out)
        for k in ("main", "v"):
            files = {}
            for cls, ext in (("rInitPosSet", "xfs"), ("rObjSet", "osf")):
                for nm, _ in stock[k].get(cls, []):
                    p = os.path.join(ip_out, base(nm) + "." + ext)
                    if os.path.exists(p):
                        files[base(nm) + "." + cls] = p
            put(A[k], files)

        print("light + camera")
        li, lo = W("light", "in"), W("light", "out")
        shutil.rmtree(W("light"), ignore_errors=True); os.makedirs(li)
        for cls, items in stock["main"].items():
            for nm, data in items:
                b = base(nm)
                if (cls == "rScheduler" and ("_Light" in b or "_filter" in b.lower() or "_Efc" in b or b == "online00_cam")) \
                        or cls == "rSceneBox2":
                    open(os.path.join(li, b + "." + cls), "wb").write(data)
        json.dump(camera(floor), open(W("cam.json"), "w"))
        lo_, hi_ = floor.lo, floor.hi
        bounds = f"{lo_[0] - 500:.0f},{lo_[2] - 500:.0f},{hi_[0] + 500:.0f},{hi_[2] + 500:.0f}"
        tool("lp2light.py", "--sun", a.sun, "--tint", a.tint, "--bounds", bounds, "--cam", W("cam.json"),
             "--sky", a.sky, "--bloom", a.bloom, "--curves", a.curves, li, lo)
        # the variable arc carries its own copies of the schedulers (the ones the game uses): both get them
        out = {f: os.path.join(lo, f) for f in os.listdir(lo)}
        put(A["main"], out)
        in_v = {base(nm).lower() + "." + cls for cls, items in stock["v"].items() for nm, _ in items}
        put(A["v"], {f: p for f, p in out.items() if f.lower() in in_v})

        json.dump(dict(name=a.name, base=0, number=0, size=a.size), open(os.path.join(pkg, "map.json"), "w"), indent=1)
        if a.thumb:
            tool("lp2thumb.py", a.thumb, os.path.join(pkg, "thumbnail.rTexture"), "--zoom", a.zoom, "--at", a.at)
        if os.path.exists(a.out):
            os.remove(a.out)
        with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
            for d, _, fs in os.walk(pkg):
                for f in sorted(fs):
                    z.write(os.path.join(d, f), os.path.relpath(os.path.join(d, f), pkg))
        print(f"{a.out}: {os.path.getsize(a.out) / 1e6:.1f} MB ({a.name}, resources under scr\\Online\\{tag})")
    finally:
        if not a.work:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
