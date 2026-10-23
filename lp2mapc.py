#!/usr/bin/env python3
"""Compile an LP2 map project (lp2project.py) into a Maps\\*.zip package.

  lp2mapc.py --game LP2_DIR PROJECT_DIR OUT.zip [--work DIR] [--library LIB]

The package is the base stock map (project base.stock, 0 = Desecration) with everything map-specific swapped:
  stage model + textures   lp2stage.py (LP1 lightmaps baked into vertex colour); the editor's level geometry
                           edits (project geometry.file, lp2pieces.py: moved / hidden / copied pieces; pieces
                           copied from other maps come from the asset library LIB, lp2library.py)
  collision                lp2col.py (atari = movement, tama = bullets), following the geometry edits
  physics (grenades...)    lp2havok.py
  spawns, VS, weapons      lp2layout.py from the project's layout.json (lifted onto the floor if asked)
  light, sky, water, cam   lp2light.py: static daylight, environment settings; written to both the main and
                           variable arcs (the variable arc's copies are the ones the game uses)
  occluders                emptied (the stock map's would cull the new geometry)
  water planes             the stock map's (effect models, its own spots) stubbed; water is a project setting
  resource paths           arcsub.py 'scr\\Online\\online00\\' -> 'scr\\Online\\<tag>\\' so the game's
                           path-keyed cache never mixes it up with the stock map or another package
Every file comes from the user's own game install and the project's assets.
"""
import argparse, json, math, os, shutil, struct, subprocess, sys, tempfile, zipfile, zlib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx, lp2col, lp2pieces, lp2project, lp2stage, mapslot, sbc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ARCS = {"main": "arcXmlTmpPC/aArea_ONLINE_00.arc", "v": "arcXmlTmpPC/variable/aArea_ONLINE_00_v.arc",
        "auto": "arcLp2Xml/autoArc/aArea_ONLINE_00.arc", "scr": "arcLp2Xml/autoArc/aArea_ONLINE_00_scr.arc"}
STAGE_DIR = "scr\\Online\\online00"
STUBS = ["online00_car1", "online00_car2", "online00_car3", "online00_car4", "online00_shadow"]
SKY_SLOT = "online00_car1"   # a stub scene model (Scr scheduler) that carries the sky (lp2sky.py)


def report(f, text=""):
    """A progress line for the editor's progress bar (0..1)."""
    print(f"@progress {f:.3f} {text}", flush=True)


def tool(name, *args, progress=None):
    """Run a tool, return its output; its '@progress F' lines are passed on mapped into progress=(lo, hi)."""
    r = subprocess.Popen([sys.executable, os.path.join(HERE, name), *map(str, args)], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    out = []
    for line in r.stdout:
        if line.startswith("@progress "):
            if progress:
                f, _, text = line[10:].strip().partition(" ")
                report(progress[0] + (progress[1] - progress[0]) * float(f), text)
        else:
            out.append(line)
    err = r.stderr.read()
    if r.wait():
        raise SystemExit(f"{name} failed:\n{''.join(out)}{err}")
    return "".join(out)


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


def stock_package(game, pkg, stock):
    native = os.path.join(game, "nativePC")
    for rel in mapslot.map_files(native, stock):
        s = os.path.join(native, rel)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(pkg, "nativePC", rel))
        elif os.path.exists(s):
            os.makedirs(os.path.dirname(os.path.join(pkg, "nativePC", rel)), exist_ok=True)
            shutil.copyfile(s, os.path.join(pkg, "nativePC", rel))
    for arc, name, cls, ext in mapslot.BOOT_RESOURCES:  # per-map resources the game also reads loose
        n = name.format(stock)
        data = next(d for x, d in entries(os.path.join(native, arc))[cls] if x.lower() == n.lower())
        out = os.path.join(pkg, "nativePC", *n.split("\\")) + "." + ext
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(data)


def build_scr(stock_scr, stage_out, dst):
    """The stock _scr archive with the stock stage textures dropped and ours added."""
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


def csv(v):
    return ",".join(f"{x:g}" for x in v)


def rebuild_physics(src, template, out, pieces, geo, library, project=None):
    """the physics mesh with the pieces' edits (moved / hidden / copied triangles follow their atoms, like the
    collision) and other maps' pieces' bullet collision, with a new MOPP tree -> a log line"""
    import lp2havok, lp2mopp
    verts, tris, _, _ = lp2havok.read(open(src, "rb").read())
    V = np.asarray(verts, np.float64) * 100   # lp2pieces works in cm (the collision's units)
    groups = []
    for i in range(0, len(tris), 16000):  # collision groups hold at most 65535 vertices
        T = np.asarray(tris[i:i + 16000], np.int64)
        used, inv = np.unique(T, return_inverse=True)
        groups.append(dict(verts=[tuple(x) for x in V[used]], tris=[(tuple(int(k) for k in t), 0) for t in inv.reshape(-1, 3)]))
    groups, (mv, dr, cp) = lp2pieces.apply_collision(groups, *pieces, geo)
    groups += lp2pieces.foreign_collision(library, geo, "lp1_bullet", project)
    verts, tris = [], []
    for g in groups:
        base = len(verts)
        verts += [tuple(c / 100 for c in v) for v in g["verts"]]
        tris += [(a + base, b + base, c + base) for (a, b, c), _ in g["tris"]]
    info, code = lp2mopp.build(verts, tris)
    found, n = lp2mopp.check(verts, tris, info, code, 2000)
    if found != n:
        raise SystemExit(f"rebuilt physics tree misses {n - found} of {n} sampled triangles")
    open(out, "wb").write(lp2havok.write(open(template, "rb").read(), verts, tris, info, code))
    return f"physics rebuilt: {len(tris)} triangles ({mv} moved, {dr} dropped, {cp} copied), MOPP {len(code)} bytes"


def sky_sources(game, folder, p, sky, stage, A, log=print):
    """the sky (lp2sky.py) as the SKY_SLOT scene model with its textures in the stage folder, and that model's
    mLightGroup 0 (unlit, as stock skies) in the Scr schedulers"""
    import lp2col, lp2light
    out = os.path.join(stage, *STAGE_DIR.split("\\"))
    if sky["type"] == "stock":
        log("  " + tool("lp2sky.py", "--game", game, "stock", sky["map"], out).strip())
    else:
        V = np.array([v for g in lp2col.read_sbc1(open(lp2project.path(folder, p["collision"]["lp1_move"]), "rb").read())
                      for v in g["verts"]])
        lo, hi = V.min(0), V.max(0)
        centre = [(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2]
        log("  " + tool("lp2sky.py", "--game", game, "panorama", lp2project.path(folder, sky["image"]), out,
                        "--centre", csv(centre), "--brightness", sky.get("brightness", 1.0)).strip())
    for k in ("scr", "v"):
        files = {}
        for nm, b in entries(A[k]).get("rScheduler", []):
            if "_scr" not in base(nm).lower():
                continue
            b = bytearray(b)
            for t in lp2light.tracks(b):
                if t["obj"] == SKY_SLOT and t["name"] == "mLightGroup" and t["keys"]:
                    struct.pack_into("<I", b, t["v"], 0)
            q = os.path.join(stage, *nm.split("\\")) + ".rScheduler"
            os.makedirs(os.path.dirname(q), exist_ok=True)
            open(q, "wb").write(bytes(b))
            files[base(nm) + ".rScheduler"] = q
        if k == "v":
            put(A["v"], files)


def compile_project(game, folder, out_zip, work=None, log=print, library=None):
    p = lp2project.load(folder)
    bad = lp2project.check(folder)
    if bad:
        raise SystemExit(f"{folder}: " + "; ".join(bad))
    P = lambda rel: lp2project.path(folder, rel)
    info, env, stock_no = p["info"], p["environment"], p["base"].get("stock", 0)
    if stock_no != 0:
        raise SystemExit("base.stock: only stock map 0 (Desecration) is supported so far")
    tag = info["tag"]
    keep = work is not None
    work = work or tempfile.mkdtemp(prefix="lp2mapc")
    os.makedirs(work, exist_ok=True)
    pkg = os.path.join(work, "pkg")
    shutil.rmtree(pkg, ignore_errors=True)
    W = lambda *q: os.path.join(work, *q)
    try:
        log(f"stock map {stock_no:02d} -> {pkg}")
        stock_package(game, pkg, stock_no)
        A = {k: os.path.join(pkg, "nativePC", v) for k, v in ARCS.items()}
        stock = {k: entries(v) for k, v in A.items()}
        tmpl = {}
        os.makedirs(W("tmpl"), exist_ok=True)
        for k, cls, name in (("scr", "rModel", "online00"), ("scr", "rCollision", "atarionline00"),
                             ("scr", "rCollision", "tamaonline00"), ("v", "rHkCollision", "havonline00")):
            tmpl[name] = W("tmpl", name + "." + cls)
            open(tmpl[name], "wb").write(next(d for n, d in stock[k][cls] if base(n).lower() == name))

        models = [P(m) for m in p["stage"]["lp1_models"]]
        log("stage model: " + ", ".join(os.path.basename(m).split(".")[0] for m in models))
        stage = W("stage")
        shutil.rmtree(stage, ignore_errors=True)
        report(0.05, "stage model")
        tool("lp2stage.py", "--template", tmpl["online00"], "--out", stage, "--tex-dir", STAGE_DIR,
             "--light", p["stage"].get("light_scale", 0.5), *sum((["--empty", s] for s in STUBS), []), *models,
             progress=(0.05, 0.55))
        geo = lp2pieces.load_geometry(P(p["geometry"]["file"])) if p.get("geometry") else {}
        pieces = None
        if lp2pieces.edited(geo):  # the editor's moved / hidden / copied level geometry
            report(0.56, "level geometry edits")
            model = os.path.join(stage, *STAGE_DIR.split("\\"), "online00.rModel")
            S = lp2pieces.read_stage(model)
            per_mesh, n = lp2pieces.atoms(S)
            meshes = lp2pieces.apply_stage(S, per_mesh, geo)
            tex, mats = S["textures"], S["materials"]
            if lp2pieces.foreign_copies(geo):   # pieces from other maps (the editor's asset library)
                tex, mats, meshes = lp2pieces.merge_foreign(S, meshes, geo, library, os.path.dirname(model), log, folder)
            tex, mats, meshes = lp2pieces.prune(tex, mats, meshes, os.path.dirname(model), log)
            lp2stage.write_stage(model, tex, mats, meshes)
            pieces = (S, per_mesh, n)
            log(f"  geometry edits: {len(geo.get('xf') or {})} atoms moved, {len(geo.get('hidden') or [])} hidden, "
                f"{len(geo.get('copies') or [])} copies")
        sky = env.get("skybox") or {"type": "map"}
        if sky.get("type") in ("stock", "panorama"):
            report(0.58, "sky")
            sky_sources(game, folder, p, sky, stage, A, log)
        build_scr(A["scr"], stage, A["scr"])
        # the stock map's water planes (effect models, its spots only) -> the stub; water is a project setting
        stub = os.path.join(stage, *STAGE_DIR.split("\\"), STUBS[-1] + ".rModel")
        put(A["main"], {"\\o00water.rModel": stub, "\\o00water2.rModel": stub})

        for k, arc in A.items():  # own resource paths
            tool("arcsub.py", arc, arc + ".new", r"scr\\online\\online00\\", "scr\\\\Online\\\\%s\\\\" % tag)
            os.replace(arc + ".new", arc)

        log("collision + physics")
        report(0.6, "collision")
        files = {}
        for key, n in (("lp1_move", "atarionline00"), ("lp1_bullet", "tamaonline00")):
            out = W(n + ".rCollision")
            if pieces:
                groups = lp2col.read_sbc1(open(P(p["collision"][key]), "rb").read())
                groups, (mv, dr, cp) = lp2pieces.apply_collision(groups, *pieces, geo)
                extra = lp2pieces.foreign_collision(library, geo, key, folder)
                groups += extra
                if extra:
                    log(f"  {n}: {sum(len(g['tris']) for g in extra)} triangles from other maps' pieces")
                data, _ = lp2col.write_lp2(groups, open(tmpl[n], "rb").read())
                open(out, "wb").write(data)
                log(f"  {n}: {mv} triangles moved, {dr} dropped, {cp} copied with the geometry")
            else:
                log("  " + tool("lp2col.py", P(p["collision"][key]), tmpl[n], out).strip().split(": ", 1)[1])
            files[f"{tag}\\{n}.rCollision"] = out
        if pieces and p["collision"].get("rebuild_physics"):
            log("  " + rebuild_physics(P(p["collision"]["lp1_physics"]), tmpl["havonline00"], W("hav.rHkCollision"),
                                       pieces, geo, library, folder))
        else:
            if pieces:
                log("  physics (grenades, debris) keeps the original geometry (collision.rebuild_physics is off)")
            log("  " + tool("lp2havok.py", P(p["collision"]["lp1_physics"]), tmpl["havonline00"], W("hav.rHkCollision")).strip().split(": ", 1)[1])
        put(A["scr"], files)
        put(A["v"], {**files, "havokdata\\havonline00.rHkCollision": W("hav.rHkCollision")})
        occ = bytearray(next(d for n, d in stock["main"]["rOccluder"])); struct.pack_into("<I", occ, 8, 0)
        open(W("occ.rOccluder"), "wb").write(occ)
        put(A["main"], {"aArea_ONLINE_00_occ.rOccluder": W("occ.rOccluder")})

        report(0.75, "layout")
        log("layout")
        floor = Floor(W("atarionline00.rCollision"))
        layout = json.load(open(P(p["layout"]["file"])))
        if p["layout"].get("lift"):
            n, bad = lift(layout, floor)
            log(f"  {n} markers moved onto the floor, {bad} with no floor below")
        json.dump(layout, open(W("layout.json"), "w"), indent=1)
        ip_in, ip_out = W("ip", "in"), W("ip", "out")
        shutil.rmtree(W("ip"), ignore_errors=True); os.makedirs(ip_in)
        for k in ("main", "v"):
            for cls, ext in (("rInitPosSet", "xfs"), ("rObjSet", "osf")):
                for nm, data in stock[k].get(cls, []):
                    open(os.path.join(ip_in, base(nm) + "." + ext), "wb").write(data)
        tool("lp2layout.py", *(["--lp1-vs"] if p["layout"].get("lp1_vs") else []), W("layout.json"), ip_in, ip_out)
        for k in ("main", "v"):
            files = {}
            for cls, ext in (("rInitPosSet", "xfs"), ("rObjSet", "osf")):
                for nm, _ in stock[k].get(cls, []):
                    q = os.path.join(ip_out, base(nm) + "." + ext)
                    if os.path.exists(q):
                        files[base(nm) + "." + cls] = q
            put(A[k], files)

        report(0.85, "light, sky, water")
        log("light, sky, water, camera")
        li, lo = W("light", "in"), W("light", "out")
        shutil.rmtree(W("light"), ignore_errors=True); os.makedirs(li)
        for cls, items in stock["main"].items():
            for nm, data in items:
                b = base(nm)
                if (cls == "rScheduler" and ("_Light" in b or "_filter" in b.lower() or "_Efc" in b or b == "online00_cam")) \
                        or cls == "rSceneBox2":
                    open(os.path.join(li, b + "." + cls), "wb").write(data)
        json.dump(env["camera"] or camera(floor), open(W("cam.json"), "w"))
        bounds = f"{floor.lo[0] - 500:.0f},{floor.lo[2] - 500:.0f},{floor.hi[0] + 500:.0f},{floor.hi[2] + 500:.0f}"
        curves = ";".join(f"{c}:{csv(v)}" for c, v in env["curves"].items())
        light_env = {k: env.get(k) for k in ("sun_colour", "sky_colour", "ground_colour", "ambient", "scatter")}
        light_env["lights"] = p.get("lights") or []
        json.dump(light_env, open(W("light_env.json"), "w"))
        tool("lp2light.py", "--sun", csv(env["sun"]), "--tint", csv(env["tint"]), "--bounds", bounds, "--cam", W("cam.json"),
             "--sky", csv(env["sky"]), "--bloom", csv(env["bloom"]), "--curves", curves,
             *(["--keep-colours"] if env["colours"] == "stock" else []),
             *(["--keep-atmosphere"] if env["atmosphere"] == "stock" else []),
             *(["--water", env["water"]] if env["water"] is not None else []), "--env", W("light_env.json"), li, lo)
        out = {f: os.path.join(lo, f) for f in os.listdir(lo)}
        put(A["main"], out)
        in_v = {(base(nm) + "." + cls).lower() for cls, items in stock["v"].items() for nm, _ in items}
        put(A["v"], {f: q for f, q in out.items() if f.lower() in in_v})

        json.dump(dict(name=info["name"], base=0, number=0, size=info["size"]), open(os.path.join(pkg, "map.json"), "w"), indent=1)
        th = info.get("thumbnail")
        if th:
            tool("lp2thumb.py", P(th["image"]), os.path.join(pkg, "thumbnail.rTexture"), "--zoom", th.get("zoom", 1),
                 "--at", csv(th.get("at", [0.5, 0.5])))
        report(0.92, "writing the package")
        if os.path.exists(out_zip):
            os.remove(out_zip)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for d, _, fs in os.walk(pkg):
                for f in sorted(fs):
                    z.write(os.path.join(d, f), os.path.relpath(os.path.join(d, f), pkg))
        report(1.0, "done")
        log(f"{out_zip}: {os.path.getsize(out_zip) / 1e6:.1f} MB ({info['name']}, resources under scr\\Online\\{tag})")
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--work")
    ap.add_argument("--library", help="the editor's asset library (lp2library.py), for pieces copied from other maps")
    ap.add_argument("project")
    ap.add_argument("out")
    a = ap.parse_args()
    compile_project(a.game, a.project, a.out, a.work, library=a.library)


if __name__ == "__main__":
    main()
