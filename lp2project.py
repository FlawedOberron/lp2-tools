#!/usr/bin/env python3
"""LP2 map project: the editable form of a custom map (what the Map Editor saves), and the LP1 importer.

  lp2project.py import-lp1 sNNN.arc OUT_DIR --name "Area 921" [--tag T] [--size S] [--layout JSON] [--exclude TEXT] [--game LP2_DIR]
  lp2project.py import-lp2 NN OUT_DIR --name "Kraftwerk edit" --game LP2_DIR --library LIB [--tag T] [--size S]
  lp2project.py new OUT_DIR --name "Arena" --game LP2_DIR [--tag T] [--size S] [--ground M]
  lp2project.py check PROJECT_DIR

A project is a folder: project.json + layout.json + assets/. lp2mapc.py compiles it to a Maps\\*.zip package.
Paths inside project.json are relative to the folder.

project.json (format "lp2map", version 1):
  info         name, tag (8-character resource folder, unique per package), size (small / medium / large),
               thumbnail: null or {image, zoom, at: [x, y]}
  base         stock: the stock online map the package is built on (0 = Desecration: shaders, effects, sounds)
  stage        lp2_stage (an LP2 map's stage, converted by lp2stockmaps.py into the asset library, copied: its
               online00.rModel + textures in lp2stage.py's output layout), lp2_map (its number), or
               lp1_models: LP1 stage models (lp2stage.py; textures beside them), light_scale (LP1 lightmap
               -> vertex colour), light_balance (0..1, default 1: the baked light's colour cast removed, its
               average made grey), exclude: name parts left out
  collision    lp1_move / lp1_bullet (LP1 atari / tama), lp1_physics (LP1 havok packfile) or lp2_physics (an LP2 map's own rHkCollision),
               rebuild_physics (true: the physics follows edited pieces, new MOPP tree; lp2mopp.py); neither physics
               file (a new empty map): the physics is built from the bullet collision with the pieces' edits
  layout       layout.json (blender_lp2_map_markers.py / lp1points.py format: sets of points + objects per
               layout variant); lift: true puts markers onto the floor at compile time (LP1 markers sit low)
  geometry     optional: {file: geometry.json}, the editor's level geometry edits (lp2pieces.py: moved,
               hidden and copied pieces of the built stage, and their grouping; a copy with "map": "lp1/s900"
               is a piece of another map, from the editor's asset library)
  environment  sun (direction towards it), tint, sky, bloom, curves {R,G,B: [[x0..x3], [y0..y3]]: 4 points, input x ->
               output y; the old flat 4-number form only ever set x and reads as neutral}, colours ("grey" | "stock"),
               atmosphere ("clear" = online01's | "stock"), water (null or height in cm), camera (null = an
               orbit round the map, or {cam: [[x,y,z] x4], tgt: [...]}), kill_floor (null or height in cm; set in
               the editor, not used by the game until the DLL's map volumes exist);
               sun_colour / sky_colour / ground_colour / ambient (null = the stock ones, grey: else absolute RGB,
               brightness included: the sun's light, the hemisphere sky light from above / below, the ambient),
               scatter (null = online01's clear sky, else {mpAreaLScattering track: value}: mRaylieghScattering,
               mMeiScattering, mMeiDirective, mDensity, mSunColor), skybox ({type: "map"} = the stage's own,
               {type: "stock", map: "06"}, {type: "panorama", image, brightness}: lp2sky.py)
  lights       placed lights: [{type point | spot, pos [cm], colour, brightness, start, end; spot: dir, cone,
               spread (degrees)}] (lp2light.py add_lights)
"""
import argparse, json, os, shutil, subprocess, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FORMAT, VERSION = "lp2map", 1
ENVIRONMENT = dict(sun=[0.472, 0.848, 0.241], tint=[0.93, 0.97, 1.1], sky=[8.5, 9.2, 10], bloom=[0.42, 0.45, 0.5],
                   curves=None,
                   colours="grey", atmosphere="clear", water=None, camera=None, sun_colour=None, sky_colour=None,
                   ground_colour=None, ambient=None, scatter=None, skybox=None)
NEUTRAL_CURVE = [[0, 0.333, 0.667, 1], [0, 0.333, 0.667, 1]]


def curves(env):
    """environment.curves -> {R, G, B: [[x0..x3], [y0..y3]]}; missing or old-form channels are neutral"""
    c = env.get("curves") if isinstance(env.get("curves"), dict) else {}
    ok = lambda v: isinstance(v, list) and len(v) == 2 and all(isinstance(h, list) and len(h) == 4 for h in v)
    return {ch: c[ch] if ok(c.get(ch)) else NEUTRAL_CURVE for ch in "RGB"}


LP1_MODEL, LP1_COLLISION, LP1_HAVOK = 0x1041bd9e, 0x3900dad0, 0x3c3d0c05


def load(folder):
    p = json.load(open(os.path.join(folder, "project.json")))
    if p.get("format") != FORMAT or p.get("version", 0) > VERSION:
        raise SystemExit(f"{folder}: not an {FORMAT} v{VERSION} project")
    p["environment"] = {**ENVIRONMENT, **p.get("environment", {})}
    return p


def save(folder, p):
    json.dump(p, open(os.path.join(folder, "project.json"), "w"), indent=1)


def path(folder, rel):
    return rel if os.path.isabs(rel) else os.path.join(folder, *rel.split("/"))


def check(folder):
    """Every file the project names exists: [] or the problems."""
    p, bad = load(folder), []
    need = list(p["stage"].get("lp1_models", [])) + [v for k, v in p["collision"].items() if isinstance(v, str)] + [p["layout"]["file"]]
    if p["info"].get("thumbnail"):
        need.append(p["info"]["thumbnail"]["image"])
    bad += [f"missing {r}" for r in need if not os.path.exists(path(folder, r))]
    if len(p["info"].get("tag", "")) != 8:
        bad.append("info.tag must be 8 characters")
    return bad


def import_lp1(arc, out, name, tag=None, size="large", layout=None, exclude=(), game=None):
    """An LP1 (PC / Colonies 360) stage archive -> a project: its stage models (+ textures), collision, physics
    and layout (lp1points.py, or an authored layout JSON)."""
    sid = os.path.basename(arc).split(".")[0].lower()
    tag = tag or ("lp1" + sid).ljust(8, "_")
    if len(tag) != 8:
        raise SystemExit("--tag must be 8 characters (it replaces 'online00')")
    os.makedirs(out, exist_ok=True)
    lp1 = os.path.join(out, "assets", "lp1")
    shutil.rmtree(lp1, ignore_errors=True)
    d, got = open(arc, "rb").read(), {}
    for n, h, cs, ds, fl, o in arcx.entries(d):
        if n.lower().startswith(("scr\\", "havokdata\\")):
            p = os.path.join(lp1, *n.lower().split("\\")) + f".{h:#010x}"
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(zlib.decompress(d[o:o + cs]) if cs != ds else d[o:o + cs])
            got.setdefault(h, []).append(os.path.relpath(p, out).replace(os.sep, "/"))
    models = sorted(p for p in got.get(LP1_MODEL, []) if not any(x in os.path.basename(p) for x in exclude))
    col = {os.path.basename(p).split(".")[0][:4]: p for p in got.get(LP1_COLLISION, [])}
    hav = next(iter(got.get(LP1_HAVOK, [])), None)
    if not models or set(col) != {"atar", "tama"} or not hav:
        raise SystemExit(f"{arc}: expected stage models, atari + tama collision and havok data")
    if layout:
        shutil.copyfile(layout, os.path.join(out, "layout.json"))
        lp1_vs = False
    else:
        r = subprocess.run([sys.executable, os.path.join(HERE, "lp1points.py"), arc, os.path.join(out, "layout.json")],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"lp1points.py failed:\n{r.stdout}{r.stderr}")
        lp1_vs = True
    p = dict(format=FORMAT, version=VERSION,
             info=dict(name=name, tag=tag, size=size, thumbnail=None),
             base=dict(stock=0),
             stage=dict(lp1_models=models, light_scale=0.5),
             collision=dict(lp1_move=col["atar"], lp1_bullet=col["tama"], lp1_physics=hav),
             layout=dict(file="layout.json", lift=True, lp1_vs=lp1_vs),
             environment=dict(ENVIRONMENT),
             source=dict(lp1=os.path.basename(arc)))
    save(out, p)
    if game and lp1_vs:   # LP1 layout -> explicit LP2 layout (lp2convert.py)
        import lp2convert
        lay = json.load(open(os.path.join(out, "layout.json")))
        lp2convert.convert(lay, game)
        lp2convert.map_vs(lay)
        json.dump(lay, open(os.path.join(out, "layout.json"), "w"), indent=1)
    return p


SKY_MAPS = ("03", "06", "07", "10", "12", "15")   # stock maps with a sky model (the editor's lighting.gd)


def import_lp2(num, out, name, game, library, tag=None, size="large"):
    """One of LP2's online maps -> a project built like an LP1 port (on Desecration): its stage and collision from
    the asset library (lp2stockmaps.py: the stage format, collision as SBC1), its own physics and its spawns,
    VS, pickups and data posts (lp2layout.stock_layout). The stock lightmaps aren't kept: the light is baked."""
    import lp2layout, lp2mapc, lp2sound
    nn = "%02d" % int(num)
    lib = os.path.join(library, "lp2", "map" + nn)
    if not os.path.exists(os.path.join(lib, ".preview", "stage")):
        raise SystemExit(f"{lib}: no converted stage: get the game assets in the editor first (Browser > Game assets)")
    tag = tag or ("lp2o" + nn).ljust(8, "_")
    if len(tag) != 8:
        raise SystemExit("--tag must be 8 characters (it replaces 'online00')")
    os.makedirs(out, exist_ok=True)
    dst = os.path.join(out, "assets", "lp2")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(lib, ".preview", "stage"), os.path.join(dst, "stage"))
    for f in ("move.sbc1", "bullet.sbc1"):
        shutil.copyfile(os.path.join(lib, "assets", f), os.path.join(dst, f))
    native = os.path.join(game, "nativePC")
    v = lp2mapc.entries(os.path.join(native, "arcXmlTmpPC", "variable", f"aArea_ONLINE_{nn}_v.arc"))
    main_ = lp2mapc.entries(os.path.join(native, "arcXmlTmpPC", f"aArea_ONLINE_{nn}.arc"))
    hav = (v.get("rHkCollision") or [None])[0]
    if hav is None:
        raise SystemExit(f"online {nn}: no physics (rHkCollision) in its _v archive")
    open(os.path.join(dst, "physics.rHkCollision"), "wb").write(hav[1])
    files = [(lp2mapc.base(n), cls, d) for E in (main_, v) for cls in ("rInitPosSet", "rObjSet") for n, d in E.get(cls, [])]
    json.dump(lp2layout.stock_layout(files), open(os.path.join(out, "layout.json"), "w"), indent=1)
    env = dict(ENVIRONMENT)
    if nn in SKY_MAPS:
        env["skybox"] = {"type": "stock", "map": nn}
    presets = lp2sound.presets()
    rv = next((k for k in (nn, nn + "_outside") if k in presets), None)
    if rv:
        env["sound"] = {"reverb": rv}
    p = dict(format=FORMAT, version=VERSION,
             info=dict(name=name, tag=tag, size=size, thumbnail=None),
             base=dict(stock=0),
             stage=dict(lp2_stage="assets/lp2/stage", lp2_map=nn, light=dict(source="bake")),
             collision=dict(lp1_move="assets/lp2/move.sbc1", lp1_bullet="assets/lp2/bullet.sbc1",
                            lp2_physics="assets/lp2/physics.rHkCollision"),
             layout=dict(file="layout.json", lift=False, lp1_vs=False),
             environment=env,
             source=dict(lp2=nn))
    ladders = lp2layout.stock_ladders(files)
    if ladders:
        p["ladders"] = ladders   # the navmesh's ladder links (lp2navmap.add_ladders)
    save(out, p)
    return p


def new_empty(out, name, game, tag=None, size="medium", ground=100.0):
    """A new empty map: a flat ground (ground x ground m at y 0, 5 m cells, a grey blockout grid) as its
    stage and collision, made by the mesh builder (lp2mesh.py: also kept as the import "ground", placeable again),
    physics from the bullet collision (lp2mapc), and spawns only: per layout variant 16 FFA starts in a 12 m ring,
    8 per team 20 m either side, the team modes' two k30 / k31 points and 4 k40 points (no VS, pickups or posts)."""
    import math, tempfile, zlib
    if not tag:
        stem = "".join(c for c in name.lower() if c.isalnum())[:4] or "map"
        tag = (stem + "%08x" % zlib.crc32(f"{name} {os.path.abspath(out)}".encode()))[:8]
    if len(tag) != 8:
        raise SystemExit("--tag must be 8 characters (it replaces 'online00')")
    os.makedirs(out, exist_ok=True)
    # a plane of 5 m cells (vertex light: the bake's shadows need the vertices), wound counter-clockwise seen from above
    n = max(1, round(ground / 5))
    h, step = ground / 2, ground / n
    obj = os.path.join(tempfile.mkdtemp(), "ground.obj")
    with open(obj, "w") as f:
        for j in range(n + 1):
            for i in range(n + 1):
                f.write("v %g 0 %g\n" % (-h + i * step, -h + j * step))
        for j in range(n):
            for i in range(n):
                v = 1 + j * (n + 1) + i
                f.write("f %d %d %d\nf %d %d %d\n" % (v, v + n + 1, v + n + 2, v, v + n + 2, v + 1))
    mesh = os.path.join(HERE, "lp2mesh.py")
    for args in (["material", "--game", game, out, "ground", "--colour", "0.55,0.55,0.55", "--blockout"],
                 ["import", "--game", game, out, obj, "--name", "ground", "--collision", "mesh"]):
        r = subprocess.run([sys.executable, mesh] + args, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"lp2mesh.py {args[0]} failed:\n{r.stdout}{r.stderr}")
    imp = os.path.join(out, "imports", "ground")
    dst = os.path.join(out, "assets", "empty")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(imp, ".preview", "stage"), os.path.join(dst, "stage"))
    for f in ("move.sbc1", "bullet.sbc1"):
        shutil.copyfile(os.path.join(imp, "assets", "collision.sbc1"), os.path.join(dst, f))
    # one set for all four start-file variants (the game picks one per match): spawns placed once are used every time
    import lp2layout
    sets = [{"ids": ["00", "01", "02", "03"], "explicit": True, "points": lp2layout.default_points(), "objects": []}]
    json.dump({"explicit": True, "lp2": False, "units": "cm, LP2 map space (Y up)", "sets": sets},
              open(os.path.join(out, "layout.json"), "w"), indent=1)
    p = dict(format=FORMAT, version=VERSION,
             info=dict(name=name, tag=tag, size=size, thumbnail=None),
             base=dict(stock=0),
             stage=dict(lp2_stage="assets/empty/stage", lp2_map="empty", light=dict(source="bake")),
             collision=dict(lp1_move="assets/empty/move.sbc1", lp1_bullet="assets/empty/bullet.sbc1"),
             layout=dict(file="layout.json", lift=False, lp1_vs=False),
             environment=dict(ENVIRONMENT, kill_floor=-3000.0),
             source=dict(empty=ground))
    save(out, p)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import-lp1")
    i.add_argument("arc"); i.add_argument("out"); i.add_argument("--name", required=True)
    i.add_argument("--tag"); i.add_argument("--size", default="large", choices=("small", "medium", "large"))
    i.add_argument("--layout"); i.add_argument("--exclude", action="append", default=[])
    i.add_argument("--game", help="LP2 folder: convert the LP1 layout to an explicit LP2 one (lp2convert.py)")
    l2 = sub.add_parser("import-lp2")
    l2.add_argument("num"); l2.add_argument("out"); l2.add_argument("--name", required=True)
    l2.add_argument("--game", required=True); l2.add_argument("--library", required=True)
    l2.add_argument("--tag"); l2.add_argument("--size", default="large", choices=("small", "medium", "large"))
    n = sub.add_parser("new")
    n.add_argument("out"); n.add_argument("--name", required=True); n.add_argument("--game", required=True)
    n.add_argument("--tag"); n.add_argument("--size", default="medium", choices=("small", "medium", "large"))
    n.add_argument("--ground", type=float, default=100.0, help="ground slab side, metres")
    c = sub.add_parser("check")
    c.add_argument("project")
    a = ap.parse_args()
    if a.cmd == "import-lp1":
        p = import_lp1(a.arc, a.out, a.name, a.tag, a.size, a.layout, a.exclude, a.game)
        print(f"{a.out}: project \"{p['info']['name']}\" ({len(p['stage']['lp1_models'])} stage models, tag {p['info']['tag']})")
    elif a.cmd == "import-lp2":
        p = import_lp2(a.num, a.out, a.name, a.game, a.library, a.tag, a.size)
        print(f"{a.out}: project \"{p['info']['name']}\" (LP2 online {p['stage']['lp2_map']}, tag {p['info']['tag']})")
    elif a.cmd == "new":
        p = new_empty(a.out, a.name, a.game, a.tag, a.size, a.ground)
        print(f"{a.out}: new empty project \"{p['info']['name']}\" (tag {p['info']['tag']})")
    else:
        bad = check(a.project)
        print("\n".join(bad) if bad else "ok")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
