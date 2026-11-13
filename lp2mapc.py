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
  base map leftovers       nothing visible of the stock map stays (lp2clean.py, lp2scenebox.neutral, lp2layout.py):
                           its gimmicks (Desecration's windmill and om8322s) and posts, scenery-list effects (water
                           planes, falling ash), placed field effects, per-zone fog / weather / env textures (plain
                           defaults, or the project's environment.fog), radar images (blank), environment cube (grey)
  water planes             the stock map's (effect models, its own spots) stubbed; water is a project setting
  sound zones              reverb presets + zones from the project's sound volumes (lp2sound.py; the game's own
                           files, no xlive mod)
  resource paths           arcsub.py 'scr\\Online\\online00\\' -> 'scr\\Online\\<tag>\\' so the game's
                           path-keyed cache never mixes it up with the stock map or another package
Every file comes from the user's own game install and the project's assets.
"""
import argparse, hashlib, json, math, os, re, shutil, struct, subprocess, sys, tempfile, zipfile, zlib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx, lp2bake, lp2clean, lp2col, lp2pieces, lp2project, lp2scenebox, lp2stage, lp2weather, mapslot, sbc  # noqa: E402
import lp2radar, lp2sound  # noqa: E402

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


def put(arc, files, add=False):
    """arcput.py in place: files = {NAME.CLASS: path}; add: names (full paths) not in it become new entries."""
    if files:
        tool("arcput.py", *(["--add"] if add else []), arc, arc + ".new", *(f"{k}={v}" for k, v in files.items()))
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
        data = next((d for x, d in entries(os.path.join(native, arc)).get(cls, []) if x.lower() == n.lower()), None)
        if data is None:  # not every map has each (online 09 has no MaterialSkipList)
            continue
        out = os.path.join(pkg, "nativePC", *n.split("\\")) + "." + ext
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(data)


def copy_lp2_stage(src, dst):
    """an LP2 map's converted stage (online00.rModel + textures, lp2stockmaps.py) as lp2stage.py's output: + the stubs"""
    shutil.copytree(src, dst)
    d = os.path.join(dst, *STAGE_DIR.split("\\"))
    S = lp2pieces.read_stage(os.path.join(d, "online00.rModel"))
    lp2stage.write_empties(d, S["textures"], S["materials"], STUBS)


def volume_local(v):
    """a project volume {"pos": centre of its floor (cm), "size": [x, y, z] (cm), "yaw": degrees about y} -> min, max
    of the box before its yaw (it turns about its centre; map.json volumes carry "yaw" beside them)"""
    (x, y, z), (sx, sy, sz) = v["pos"], v.get("size", [1000, 1000, 1000])
    return [x - sx / 2, y, z - sz / 2], [x + sx / 2, y + sy, z + sz / 2]


def volume_parts(v):
    """a volume's boxes as separate volumes with its effects: the main one, then each of "boxes" ({"pos": floor centre
    relative to the volume's pos in its turned frame, "size"}) turned and placed in the map"""
    main = {k: x for k, x in v.items() if k != "boxes"}
    out = [main]
    a = math.radians(volume_yaw(v))
    c, s = math.cos(a), math.sin(a)
    x, y, z = v["pos"]
    for b in v.get("boxes", []):
        lx, ly, lz = b["pos"]
        out.append(dict(main, pos=[x + lx * c + lz * s, y + ly, z - lx * s + lz * c], size=list(b["size"])))
    return out


def all_parts(p):
    return [q for v in p.get("volumes", []) for q in volume_parts(v)]


def volume_yaw(v):
    return float(v.get("yaw", 0.0)) % 360.0


def volume_corners(v):
    """the box's 4 x / z corners, turned by its yaw (the editor's: Godot's rotation about y, game axes)"""
    (x, _y, z), (sx, _sy, sz) = v["pos"], v.get("size", [1000, 1000, 1000])
    a = math.radians(volume_yaw(v))
    c, s = math.cos(a), math.sin(a)
    return [(x + lx * c + lz * s, z - lx * s + lz * c)
            for lx, lz in ((-sx / 2, -sz / 2), (sx / 2, -sz / 2), (sx / 2, sz / 2), (-sx / 2, sz / 2))]


def volume_box(v):
    """the volume's world-axis bounds (its corners after the yaw) -> min, max"""
    lo, hi = volume_local(v)
    cs = volume_corners(v)
    return ([min(c[0] for c in cs), lo[1], min(c[1] for c in cs)],
            [max(c[0] for c in cs), hi[1], max(c[1] for c in cs)])


def barrier_groups(p):
    """barrier volumes ("barrier": true) as closed boxes for the movement collision only: players and VS stop,
    bullets (and the grapple, which aims with the bullet collision) pass"""
    return [lp2col.box(volume_corners(v), volume_local(v)[0][1], volume_local(v)[1][1]) for v in all_parts(p)
            if v.get("barrier")]


def volume_kill(v):
    """a volume's effects combine: "kill": true, "gravity": x, "post": {...} (older projects: "type")"""
    return bool(v.get("kill")) or v.get("type") == "kill"


def volume_gravity(v):
    return float(v["gravity"]) if "gravity" in v and v.get("type") != "kill" else None


def cache_dir(kind):
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "lp2-tools", kind)


def collision_key(src, tmpl, models, geo, kill, kills, library):
    """a cache key for one built rCollision: its inputs' bytes, the settings and the collision code"""
    h = hashlib.sha1()
    for f in [src, tmpl, *models] + [os.path.join(HERE, m) for m in ("lp2col.py", "lp2pieces.py", "lp2stage.py")]:
        h.update(open(f, "rb").read())
        h.update(b"\0")
    h.update(json.dumps([geo, kill, kills, str(library)], sort_keys=True, default=str).encode())
    return h.hexdigest()


def cache_put(path, src):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, path)


def no_weather_volumes(p):
    """weather limiter volumes ("weather": % of the map's weather inside; older "no_weather": true = 0) join
    environment.weather.volumes (lp2weather's boxes: "pos" the centre, cm, "amount" %)"""
    vs = [v for v in all_parts(p) if "weather" in v or v.get("no_weather")]
    w = p.get("environment", {}).get("weather")
    if vs and isinstance(w, dict):
        w["volumes"] = list(w.get("volumes") or []) + [
            dict(pos=[v["pos"][0], v["pos"][1] + v["size"][1] / 2, v["pos"][2]], size=list(v["size"]),
                 yaw=volume_yaw(v), amount=max(0.0, min(100.0, float(v.get("weather", 0.0))))) for v in vs]


# visual scripting (the editor's scripts.gd): node type -> (input ports, output ports, props kept)
SCRIPT_TYPES = {
    "start": ((), ("then",), ()),
    "enter": ((), ("entered", "left"), ("who",)),
    "timer": (("start", "stop"), ("tick",), ("seconds", "max_seconds", "repeat", "autostart")),
    "delay": (("in",), ("then",), ("seconds", "max_seconds")),
    "flipflop": (("in",), ("A", "B"), ()),
    "counter": (("in", "reset"), ("reached",), ("target",)),
    "set": (("in",), ("then",), ()),
    "if": (("in",), ("on", "off"), ()),
    "volume": (("on", "off", "toggle"), ("then",), ()),
    "log": (("in",), ("then",), ("text",)),
    "random": (("in",), ("then",), ("integer",)),
    "math": (("in",), ("then",), ("op",)),
    "compare": (("in",), ("yes", "no"), ("op",)),
    "setvalue": (("in",), ("then",), ("setting", "seconds")),
    "players": (("in",), ("then",), ()),
    "list": (("add", "remove", "clear"), ("then",), ()),
    "listremove": (("in",), ("then",), ("check",)),
    "listget": (("in",), ("found", "none"), ("random",)),
    "listcount": (("in",), ("then",), ()),
    "foreach": (("in",), ("each", "done"), ()),
    "playercheck": (("in",), ("yes", "no"), ("check",)),
    "playerget": (("in",), ("then",), ("stat",)),
    "playeract": (("in",), ("then",), ("action",)),
    "loop": (("in",), ("each", "done"), ()),
    "findmarkers": (("in",), ("found", "none"), ("text",)),
    "getmarker": (("in",), ("found", "none"), ("text", "random")),
    "spawn": (("in",), ("spawned", "skipped"), ("kind", "items", "random")),
    "teleport": (("in",), ("moved", "skipped"), ("random", "face")),
    "getpos": (("in",), ("then", "none"), ()),
    "vector": (("in",), ("then",), ("vecop",)),
    "switch": (("in",), ("1", "2", "3", "4", "5", "6", "default"), ("cases",)),
    "sequence": (("in",), ("1", "2", "3", "4", "5", "6"), ()),
    "gate": (("in", "open", "close", "toggle"), ("then",), ("autostart",)),
    "once": (("in", "reset"), ("then",), ()),
    "branch": (("in",), ("1", "2", "3", "4", "5", "6"), ("target",)),
    "chance": (("in",), ("yes", "no"), ()),
    "cooldown": (("in", "reset"), ("then", "blocked"), ("seconds",)),
    "zoneoutline": (("show", "hide"), ("then",), ("text", "colour", "seconds")),
    # game modes (.lp2mode, lp2mode.py; the editor's modes.gd): xlive scripts.cpp runs them on the host
    "matchstart": ((), ("then",), ()),
    "roundstart": ((), ("then",), ()),
    "roundend": ((), ("then",), ()),
    "worldupdate": ((), ("tick",), ()),
    "onkill": ((), ("then",), ()),
    "ondeath": ((), ("then",), ()),
    "onspawn": ((), ("then",), ()),
    "spawnplayer": (("in",), ("spawned", "skipped"), ("face", "random")),
    "holdplayer": (("in",), ("then",), ()),
    "eliminate": (("in",), ("then",), ()),
    "respawnrules": (("in",), ("then",), ("respawn",)),
    "queue": (("push", "push front", "pop", "remove", "clear"), ("then", "empty"), ()),
    "score": (("add", "set"), ("then",), ("scoreof",)),
    "playerinfo": (("in",), ("then",), ("info",)),
    "teamlist": (("in",), ("then",), ("alive",)),
    "endround": (("in",), (), ("scoreof",)),
    "endmatch": (("in",), (), ("scoreof",)),
    "showtext": (("in",), ("then",), ("text", "showto", "style", "font", "colour", "seconds")),
    # mode -> map: a mode's "Fire map event" runs the map script's "On mode event" nodes of the same name (text)
    "modeevent": (("in",), ("then",), ("text",)),
    "onmodeevent": ((), ("then",), ("text",)),
}
SCRIPT_VEC_NUMBER_OPS = ("length", "getx", "gety", "getz", "getyaw")   # vector ops whose result is a number
SCRIPT_VEC_B_VECTOR = ("add", "sub")                                    # ops whose B is a vector (else a number)
SCRIPT_VOLUME_NODES = ("enter", "volume", "setvalue")
# the variables a node names, by field: number ("var"), player ("player"; optional on enter), list ("list")
SCRIPT_VAR_NODES = ("set", "if", "random", "math", "listcount", "playerget", "loop", "roundstart", "roundend", "worldupdate",
                    "playerinfo")
SCRIPT_PLAYER_NODES = ("enter", "list", "listget", "foreach", "playercheck", "playerget", "playeract", "getmarker",
                       "spawn", "teleport", "onspawn", "spawnplayer", "holdplayer", "eliminate", "queue", "score",
                       "playerinfo", "teamlist", "endround", "endmatch", "showtext", "modeevent", "onmodeevent")
SCRIPT_LIST_NODES = ("players", "list", "listremove", "listget", "listcount", "foreach", "findmarkers", "queue", "teamlist")
SCRIPT_ITEM_NODES = ("list", "listget", "foreach")   # their "player" is a list entry: a marker for a markers list
SCRIPT_OPERANDS = {"set": ("a",), "random": ("a", "b"), "math": ("a", "b"), "compare": ("a", "b"), "setvalue": ("a",),
                   "listremove": ("a",), "listget": ("a",), "playercheck": ("a",), "playeract": ("a",),
                   "loop": ("a", "b"), "spawn": ("a",), "vector": ("a", "b"),
                   "switch": ("a",), "chance": ("a",), "zoneoutline": ("a",),
                   "respawnrules": ("a", "b"), "score": ("a",)}


def script_volume_ids(p):
    """volume id -> script volume number, for the volumes the scripts use"""
    out = {}
    ids = {v.get("id") for v in p.get("volumes", []) if v.get("id")}
    for n in (p.get("scripts") or {}).get("nodes", []):
        vid = n.get("volume")
        if n.get("type") in SCRIPT_VOLUME_NODES and vid in ids and vid not in out:
            out[vid] = len(out)
    return out


def script_var_name(x):
    return str(x).strip().lower()


def script_operand(x, names):
    """a node value: a number, else a variable's name -> {"var": index}"""
    try:
        return float(x)
    except (TypeError, ValueError):
        name = script_var_name(x) or "var"
        if name not in names:
            names.append(name)
        return {"var": names.index(name)}


def script_manifest(p, log=print):
    """map.json "script" for the xlive mod (scripts.cpp): {nodes: [{type, props, sid / var, a / b (number or
    {var}), out: {port: [[node, in port]]}}], volumes: count, start_off: [volume numbers], vars: count, var_names}
    and "script_volumes" (every box of a used volume, "sid")"""
    sids = script_volume_ids(p)
    src = [n for n in (p.get("scripts") or {}).get("nodes", []) if n.get("type") in SCRIPT_TYPES]
    keep, dropped = [], []
    for n in src:
        if n["type"] in SCRIPT_VOLUME_NODES and n.get("volume") not in sids:
            dropped.append(n["id"])
        else:
            keep.append(n)
    if dropped:
        log(f"  script: {len(dropped)} node(s) without a volume skipped ({', '.join(dropped)})")
    if not keep:
        return {}
    index = {n["id"]: i for i, n in enumerate(keep)}
    names = []
    kinds = {}
    # lists filled by findmarkers hold markers (their entries too); the rest players
    marker_lists = {script_var_name(n.get("list", "")) or "players" for n in keep if n["type"] == "findmarkers"}
    nodes = []

    def ref(n, field, kind, default):
        name = script_var_name(n.get(field, "")) or default
        if not name:
            return None
        if name not in names:
            names.append(name)
        if kinds.setdefault(name, kind) != kind:
            log(f"  script: variable \"{name}\" used as a {kinds[name]} and a {kind} ({n['id']})")
        return names.index(name)

    for n in keep:
        ins, outs, props = SCRIPT_TYPES[n["type"]]
        e = {"type": n["type"], "out": {}}
        for k in props:
            if k in n:
                e[k] = n[k]
        if n["type"] in SCRIPT_VOLUME_NODES:
            e["sid"] = sids[n["volume"]]
        if n["type"] in SCRIPT_VAR_NODES:
            e["var"] = ref(n, "var", "number", "var")
        if n["type"] == "getpos":
            e["var"] = ref(n, "var", "vector", "pos")
            e["from"] = "marker" if n.get("from") == "marker" else "player"
            if e["from"] == "marker":
                e["marker"] = ref(n, "marker", "marker", "spot")
            else:
                e["player"] = ref(n, "player", "player", "player")
        if n["type"] == "vector":
            op = n.get("vecop", "add")
            e["var"] = ref(n, "var", "number" if op in SCRIPT_VEC_NUMBER_OPS else "vector", "pos")
            for k in ("a", "b"):   # name the operands' kinds (numbers stay numbers)
                x = n.get(k, "")
                try:
                    float(x)
                except (TypeError, ValueError):
                    if k == "a" or op in SCRIPT_VEC_B_VECTOR:
                        ref(n, k, "vector", "pos")
            if op in ("tolocal", "fromlocal"):
                e["marker"] = ref(n, "marker", "marker", "spot")
        lname = script_var_name(n.get("list", "")) or "players"
        of_markers = lname in marker_lists
        if n["type"] in SCRIPT_PLAYER_NODES:
            marker = n["type"] in ("getmarker", "spawn") or (n["type"] in SCRIPT_ITEM_NODES and of_markers)
            v = ref(n, "player", "marker" if marker else "player", "" if n["type"] == "enter" else "player")
            if v is not None:
                e["player"] = v
        if n["type"] == "onkill":   # mode events' players
            e["player"] = ref(n, "killer", "player", "killer")
            e["victim"] = ref(n, "victim", "player", "victim")
        if n["type"] == "ondeath":
            e["player"] = ref(n, "victim", "player", "victim")
        if n["type"] == "spawnplayer":
            e["marker"] = ref(n, "marker", "marker", "spot")
        if n["type"] == "teleport":   # its "player" is who; where: "marker", or a vector ("vec")
            if n.get("to") == "vector":
                e["vec"] = ref(n, "vec", "vector", "pos")
            else:
                e["marker"] = ref(n, "marker", "marker", "spot")
        if n["type"] in SCRIPT_LIST_NODES:
            e["list"] = ref(n, "list", "markers" if of_markers else "list", "players")
        if n["type"] == "set":
            value = str(n.get("value", "toggle")).strip().lower()
            if value == "toggle":
                e["toggle"] = True
            else:
                e["a"] = 1.0 if value == "on" else 0.0 if value == "off" else script_operand(value, names)
        for k in SCRIPT_OPERANDS.get(n["type"], ()):
            if n["type"] != "set" and k in n:
                e[k] = script_operand(n[k], names)
        nodes.append(e)
    for a, port, b, inport in (p.get("scripts") or {}).get("links", []):
        if a in index and b in index and port in SCRIPT_TYPES[keep[index[a]]["type"]][1] \
                and inport in SCRIPT_TYPES[keep[index[b]]["type"]][0]:
            nodes[index[a]]["out"].setdefault(port, []).append([index[b], inport])
    start_off = sorted({sids[n["volume"]] for n in keep if n["type"] == "volume" and n.get("start_off")})
    boxes = []
    for v in all_parts(p):
        if v.get("id") in sids:
            lo, hi = volume_local(v)
            boxes.append(dict(min=lo, max=hi, sid=sids[v["id"]], **({"yaw": volume_yaw(v)} if volume_yaw(v) else {})))
    markers = []
    for v in p.get("volumes", []):
        if "marker" in v:
            markers.append({"name": script_var_name(v["marker"]), "pos": list(v["pos"]),
                            "size": list(v.get("size", [100, 200, 100])), "yaw": volume_yaw(v)})
    for t in p.get("script_tags", []):   # any object's script name (the editor's: pieces, lights, spawns, pickups, VS)
        markers.append({"name": script_var_name(t["name"]), "pos": [float(x) for x in t["pos"]],
                        "size": [float(x) for x in t.get("size", [100, 200, 100])], "yaw": float(t.get("yaw", 0.0)) % 360.0})
    natural = lambda m: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", m["name"])]
    markers.sort(key=natural)
    log(f"  script: {len(nodes)} node(s), {len(sids)} volume(s), {len(names)} variable(s), {len(markers)} marker(s)")
    return {"script_markers": markers, "script": {"nodes": nodes, "volumes": len(sids), "start_off": start_off, "vars": len(names),
                       "var_names": names, "var_kinds": [kinds.get(x, "number") for x in names]},
            "script_volumes": boxes}


def gravity_manifest(p):
    """map.json gravity and screen settings for the xlive mod (gravity.cpp, post.cpp): environment jump_packs /
    underwater / gravity, gravity volumes, post-process volumes, water volumes (water.cpp: water up to the box's top),
    damage volumes (damage.cpp: "damage": {player, vs: % of full health per second; player_kill / vs_kill: at once}),
    one-way walls (oneway.cpp: "oneway": {players, vs, bullets, grenades, akrid}: crossed along the box's arrow only),
    force volumes (force.cpp: "force": {mode, vector (m/s, or m/s per second for continuous), local, flags as one-way's}:
    map.json "force" in cm, game axes, turned by the yaw when local), spawn zones (respawn.cpp: "spawn": {team 0 / 1 / -1,
    order})"""
    env, out = p.get("environment", {}), {}
    if env.get("jump_packs"):
        out["jump_packs"] = True
    if env.get("low_gravity"):   # older projects (the xlive mod reads it as jump packs + gravity x0.3)
        out["low_gravity"] = True
    if env.get("underwater"):
        out["underwater"] = True
    if float(env.get("gravity", 1.0)) != 1.0:
        out["gravity"] = float(env["gravity"])
    vols = []
    posts = []
    water = []
    damage = []
    oneway = []
    force = []
    spawn = []
    sids = script_volume_ids(p)
    for v in all_parts(p):
        lo, hi = volume_local(v)
        turn = {"yaw": volume_yaw(v)} if volume_yaw(v) else {}   # the xlive mod tests the box turned about its centre
        if v.get("id") in sids:
            turn["sid"] = sids[v["id"]]   # scripts switch its effects (scripts.cpp)
        if v.get("water"):
            water.append(dict(min=lo, max=hi, **turn))
        if v.get("damage"):
            q = v["damage"]
            e = dict(min=lo, max=hi, player=max(0.0, float(q.get("player", 0))), vs=max(0.0, float(q.get("vs", 0))),
                     **turn)
            for k in ("player_kill", "vs_kill"):
                if q.get(k):
                    e[k] = True
            if e["player"] or e["vs"] or e.get("player_kill") or e.get("vs_kill"):
                damage.append(e)
        if v.get("oneway"):
            flags = {k: True for k in ("players", "vs", "bullets", "grenades", "akrid") if v["oneway"].get(k)}
            if flags:
                oneway.append(dict(min=lo, max=hi, **flags, **turn))
        if v.get("force"):
            q = v["force"]
            flags = {k: True for k in ("players", "vs", "bullets", "grenades", "akrid") if q.get(k)}
            x, y, z = (float(c) * 100.0 for c in q.get("vector", [0, 0, 0]))
            if q.get("local", True):   # the editor's turn (Godot's rotation about y), as volume_corners
                a = math.radians(volume_yaw(v))
                c, s_ = math.cos(a), math.sin(a)
                x, z = x * c + z * s_, -x * s_ + z * c
            mode = q.get("mode", "continuous")
            if flags and (x or y or z) and mode in ("continuous", "impulse", "velocity"):
                force.append(dict(min=lo, max=hi, mode=mode, force=[round(x, 3), round(y, 3), round(z, 3)], **flags, **turn))
        if v.get("spawn"):   # a spawn zone (xlive respawn.cpp: Spawning > Spawn Area: Zones): team 0 / 1 / -1 nobody
            q = v["spawn"]
            team = int(q.get("team", -1))
            spawn.append(dict(min=lo, max=hi, team=team if team in (0, 1) else -1, order=int(q.get("order", 0)),
                              **({"yaw": turn["yaw"]} if "yaw" in turn else {})))
        if volume_gravity(v) is not None:
            vols.append(dict(min=lo, max=hi, gravity=volume_gravity(v), **turn))
        if v.get("post"):
            q = v["post"]
            posts.append(dict(min=lo, max=hi, tint=[float(c) for c in q.get("tint", [1, 1, 1])][:3],
                              brightness=float(q.get("brightness", 1)), saturation=float(q.get("saturation", 1)),
                              contrast=float(q.get("contrast", 1)), fade=float(q.get("fade", 0.5)), **turn))
    if vols:
        out["gravity_volumes"] = vols
    if posts:
        out["post_volumes"] = posts
    if water:
        out["water_volumes"] = water
    if damage:
        out["damage_volumes"] = damage
    if oneway:
        out["oneway_volumes"] = oneway
    if force:
        out["force_volumes"] = force
    if spawn:
        out["spawn_volumes"] = spawn
    return out


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
                # the stock environment cube -> plain grey (lp2clean.neutral_cube)
                open(p, "wb").write(lp2clean.neutral_cube(data) if n.lower().endswith("_cm-01") else data)
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


def rebuild_physics(src, template, out, pieces, geo, library, project=None, bullet=None):
    """the physics mesh with the pieces' edits (moved / hidden / copied triangles follow their atoms, like the
    collision) and other maps' pieces' bullet collision, with a new MOPP tree -> a log line. src None: the
    stage's physics is its bullet collision (SBC1 file bullet; a new empty map has no physics file)"""
    import lp2col, lp2havok, lp2mopp
    if src is None:
        groups = [dict(verts=g["verts"], tris=[(t, 0) for t, _ in g["tris"]]) for g in lp2col.read_sbc1(open(bullet, "rb").read())]
    else:
        verts, tris, _, _ = lp2havok.read(open(src, "rb").read())
        V = np.asarray(verts, np.float64) * 100   # lp2pieces works in cm (the collision's units)
        groups = []
        for i in range(0, len(tris), 16000):  # collision groups hold at most 65535 vertices
            T = np.asarray(tris[i:i + 16000], np.int64)
            used, inv = np.unique(T, return_inverse=True)
            groups.append(dict(verts=[tuple(x) for x in V[used]], tris=[(tuple(int(k) for k in t), 0) for t in inv.reshape(-1, 3)]))
    mv = dr = cp = 0
    if pieces:
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


def weather_type(env):
    """environment.weather's type when it is on (lp2weather.py), else None"""
    w = env.get("weather") or {}
    return w.get("type") if w.get("type") in lp2weather.PRESETS and float(w.get("amount", 0)) > 0 else None


def weather_rates(env):
    """lp2light --weather: the strength for each effect scheduler Efc0-3 (environment.weather.layouts: on per layout,
    if the game ties them to the 4 layouts; untested). The amount (0..100) is rate 0..50, the stock range: the game
    (DX11 uPlanetEffectVFRWeather::vf80 0xde0bc0) draws 10 x rate x zone amount % particles up to rate 50; above it a
    lower zone amount makes it heavier (limiter volumes can't work) and over 989 particles none are drawn (rate 100
    drew nothing)."""
    if not weather_type(env):
        return "0"
    w = env["weather"]
    on = w.get("layouts") or [True] * 4
    rate = max(1, min(50, round(float(w.get("amount", 0)) / 2)))
    return ",".join(str(rate if on[i] else 0) for i in range(4))


def add_weather(game, A, env, W, log=print):
    """the weather's effect lists (and what they name) from its stock map into the package's main arc"""
    kind = weather_type(env)
    if not kind:
        return
    d = W("weather")
    os.makedirs(d, exist_ok=True)
    files = {}
    for i, ((n, cls), b) in enumerate(sorted(lp2weather.resources(game, kind).items())):
        q = os.path.join(d, f"{i}.{cls}")
        open(q, "wb").write(b)
        files[f"{n}.{cls}"] = q
    tool("arcput.py", "--add", A["main"], A["main"] + ".new", *(f"{k}={v}" for k, v in files.items()))
    os.replace(A["main"] + ".new", A["main"])
    w = env["weather"]
    log(f"  weather: {lp2weather.PRESETS[kind][4]}, strength {float(w.get('amount', 0)):g}, {len(files)} resources, "
        f"{len(w.get('volumes') or [])} no-weather volumes")


def off_mesh_warning(folder, p, tris, log=print):
    """the layout's spawn points with no playable navmesh under them (on a roof, outside the map, in the air): the
    game spawns players there all the same"""
    A, B, C = tris[:, 0], tris[:, 1], tris[:, 2]
    d = (B[:, 2] - C[:, 2]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 2] - C[:, 2])
    ok = np.abs(d) > 1e-6
    d = np.where(ok, d, 1)
    lay = json.load(open(lp2project.path(folder, p["layout"]["file"])))
    for k, st in enumerate(lay.get("sets", [])):
        bad = 0
        for q in st.get("points", []):
            x, y, z = q["pos"]
            l1 = ((B[:, 2] - C[:, 2]) * (x - C[:, 0]) + (C[:, 0] - B[:, 0]) * (z - C[:, 2])) / d
            l2 = ((C[:, 2] - A[:, 2]) * (x - C[:, 0]) + (A[:, 0] - C[:, 0]) * (z - C[:, 2])) / d
            l3 = 1 - l1 - l2
            h = l1 * A[:, 1] + l2 * B[:, 1] + l3 * C[:, 1]
            bad += not (ok & (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3) & (h <= y + 50) & (h >= y - 400)).any()
        if bad:
            log(f"WARNING: layout {'/'.join(map(str, st.get('ids', [k])))}: {bad} of {len(st.get('points', []))} spawn "
                f"points have no playable navmesh under them (players spawn there: roof, outside, mid-air)")


def strip_base(A, stock, env, W, log=print, radar=None):
    """the base map's own visible resources out of the package (lp2clean.py): scenery list entries (water planes,
    falling ash, underwater effect unless the project has water), placed field effects, trigger zones, the water
    scheduler, the radar map images. radar (lp2radar.build): the project's radar in their place, its floor zones
    the only trigger zones."""
    m = stock["main"]
    d = W("clean")
    os.makedirs(d, exist_ok=True)
    files, notes = {}, []
    def out(name, data):
        files[name] = os.path.join(d, name)
        open(files[name], "wb").write(data)
    weather = weather_type(env)
    for nm, b in m.get("rScrList", []):
        data, n = lp2clean.scrlist(b, env.get("water") is not None)
        if weather:
            data = lp2weather.scrlist(data, weather)
        out(base(nm) + ".rScrList", data)
        notes.append(f"{n} scenery list entries")
    for k in ("main", "v"):   # both arcs carry the trigger zones
        files_k = {}
        for nm, b in stock[k].get("rAreaHitLayout", []):
            data, n = lp2clean.areahit(b)
            if radar:
                data, n = lp2radar.zones(b, radar["planes"], radar["boxes"], *radar["height"])
            q = os.path.join(d, k + "_" + base(nm) + ".rAreaHitLayout")
            open(q, "wb").write(data)
            files_k[base(nm) + ".rAreaHitLayout"] = q
        if k == "v":
            put(A["v"], files_k)
        else:
            files.update(files_k)
            notes.append(f"{n} radar zones" if radar else f"{n} trigger zones")
    for nm, b in m.get("rFieldSet", []):
        data, n = lp2clean.fieldset(b)
        out(base(nm) + ".rFieldSet", data)
        notes.append(f"{n} placed effects")
    import lp2light
    root_only = next((b for nm, b in m.get("rScheduler", []) if len(lp2light.tracks(b)) == 1), None)
    for nm, b in m.get("rScheduler", []):
        if base(nm).lower() == "on00_water" and root_only:
            out(base(nm) + ".rScheduler", lp2clean.empty_scheduler(root_only))
            notes.append("water scheduler")
    images = {base(nm).lower(): b for nm, b in m.get("rTexture", []) if "rader_map" in nm.lower()}
    new = {}
    if radar:   # ours as _1.._n (past stock's five: new entries), the movie and its dependency list to match
        n = len(radar["images"])
        for k, img in enumerate(radar["images"]):
            nm = lp2radar.IMAGE.format(k + 1)
            q = os.path.join(d, nm + ".rTexture")
            open(q, "wb").write(lp2radar.texture(img))
            if images.pop(nm.lower(), None) is not None:
                files[nm + ".rTexture"] = q
            else:
                new[lp2radar.IMAGE_DIR + nm + ".rTexture"] = q
        movie = next(b for nm, b in m["rFlash"] if "rader_map" in nm.lower())
        out(base(lp2radar.NAME) + ".rFlash", lp2radar.movie(movie, n, radar["place"], radar["size"]))
        out(base(lp2radar.NAME) + ".rArchive", lp2radar.archive(n))
        notes.append(f"radar: {n} floor image{'s' if n > 1 else ''}")
    for nm, b in images.items():   # the rest blank
        out(nm + ".rTexture", lp2clean.blank_texture(b))
    if images and not radar:
        notes.append(f"{len(images)} radar images blanked")
    put(A["main"], files)
    put(A["main"], new, add=True)
    log("base map leftovers removed: " + ", ".join(notes))


def preload_arcs(game, osf_dir):
    """the autoArc archives for every VS (uVsXX), VS-mounted weapon and weapon pickup (uWpXX) the layouts use,
    for map.json "preload": the xlive mod adds them to the base map's preload list, which only has its own map's."""
    import objset
    auto = os.path.join(game, "nativePC", "arcLp2Xml", "autoArc")
    have = {f[:-4].lower(): f[:-4] for f in os.listdir(auto) if f.lower().endswith(".arc")}
    want = set()
    for f in sorted(os.listdir(osf_dir)):
        if not f.endswith(".osf"):
            continue
        b = open(os.path.join(osf_dir, f), "rb").read()
        counts, _, _ = objset.parse(b)
        off = 0x30
        for g in (1, 2, 3, 4):
            for _ in range(counts[g]):
                r = b[off:off + objset.SIZES[g]]
                off += objset.SIZES[g]
                if g == 1:
                    want.add("uvs%02x" % struct.unpack_from("<H", r, 0x1A)[0])
                    for i in range(4):
                        on, kind, wid = struct.unpack_from("<BBH", r, 0x120 + 5 * i)
                        if on and kind == 4:
                            want.add("uwp%02x" % wid)
                elif g == 4:
                    want.add("uwp%02x" % struct.unpack_from("<H", r, 0x1A)[0])
    return sorted(have[w] for w in want if w in have)


def script_preload(game, p):
    """the autoArc archives for what the scripts' Spawn nodes may make (uWpXX pickups, uVsXX VS)"""
    auto = os.path.join(game, "nativePC", "arcLp2Xml", "autoArc")
    have = {f[:-4].lower(): f[:-4] for f in os.listdir(auto) if f.lower().endswith(".arc")}
    want = set()
    for n in (p.get("scripts") or {}).get("nodes", []):
        if n.get("type") == "spawn":
            for i in n.get("items", []):
                want.add(("uvs%02x" if n.get("kind") == "vs" else "uwp%02x") % int(i))
    return sorted(have[w] for w in want if w in have)


NAV_INPUTS = ("base", "collision", "geometry", "layout", "source", "stage", "terrains", "volumes", "nav_settings", "nav_welds", "nav_removed", "nav_added", "nav_mesh", "ladders")


def nav_stamp(folder):
    """A hash of what the navmesh is built from: the project's parts that matter, the files they name (by content, big
    ones by size and time) and the tools. Environment, lights and so on don't count, nor does the save itself."""
    p = json.load(open(os.path.join(folder, "project.json")))
    h = hashlib.sha1()
    part = {k: p.get(k) for k in NAV_INPUTS}
    part["tag"], part["kill"] = (p.get("info") or {}).get("tag"), (p.get("environment") or {}).get("kill_floor")
    h.update(json.dumps(part, sort_keys=True).encode())
    names = {os.path.join(HERE, t) for t in ("lp2navgen.py", "lp2navmap.py")}
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x:
            q = os.path.join(folder, x)
            if os.path.isfile(q):
                names.add(q)
    walk(part)
    for q in sorted(names):
        st = os.stat(q)
        h.update(os.path.basename(q).encode())
        if st.st_size < 4 << 20:
            h.update(open(q, "rb").read())
        else:
            h.update(f"{st.st_size} {st.st_mtime_ns}".encode())
    return h.hexdigest()


def ensure_navmesh(folder, tag, library, log=print):
    """The bots' navmesh, built when it's missing or the map changed since. A failed build warns and the export goes on
    with what's there. Returns (list file, way file) or None."""
    nav, prev = os.path.join(folder, "assets", "nav"), os.path.join(folder, ".preview")
    files = (os.path.join(nav, f"List_{tag}.rAINavigationMeshList"), os.path.join(nav, f"Way_{tag}.rAIWayPoint"))
    stamp_file = os.path.join(prev, "navmesh.stamp")
    have = all(os.path.isfile(f) for f in files) and os.path.isfile(os.path.join(prev, "navmesh.bin"))
    stamp = nav_stamp(folder)
    if have and os.path.isfile(stamp_file) and open(stamp_file).read().strip() == stamp:
        log("navmesh: up to date")
        return files
    report(0.01, "navmesh")
    log("navmesh: building" + (" (the map changed)" if have else ""))
    try:
        out = tool("lp2navmap.py", folder, *(["--library", library] if library else []), progress=(0.01, 0.05))
    except SystemExit as e:
        log(f"navmesh: WARNING, the build failed, {'the last one is used' if have else 'bots will not move on this map'}: {e}")
        return files if have else None
    res = next((json.loads(l[8:]) for l in out.splitlines() if l.startswith("@result ")), None)
    if res:   # the editor shows these (it reads .preview/navmesh.json after the export)
        raw = json.load(open(os.path.join(folder, "project.json")))
        raw["navmesh"] = res
        json.dump(raw, open(os.path.join(folder, "project.json"), "w"), indent=1)
        log(f"navmesh: {res['polygons']} polygons, {res['dropped']} outside the playable area")
    return files


def add_navmesh(A, tag, files, folder, W, log=print):
    """what a bot area has and an online one doesn't: the navmesh list, way points and intelligence box, named in the
    area's scenery list. Named by the project's tag, so nothing here depends on the slot the map lands in."""
    import lp2nav
    d = W("nav")
    os.makedirs(d, exist_ok=True)
    names = {29: f"tool\\AI\\NaviMesh\\{tag}\\List_{tag}", 30: f"tool\\AI\\NaviMesh\\{tag}\\Way_{tag}", 31: f"tool\\AI\\AreaAI\\{tag}"}
    with open(os.path.join(folder, ".preview", "navmesh.bin"), "rb") as f:
        n = struct.unpack("<I", f.read(4))[0]
        tri = np.frombuffer(f.read(n * 36), "<f4").reshape(-1, 3)
    box = os.path.join(d, "box.rIntelligenceBox")
    open(box, "wb").write(lp2nav.empty_intelligence_box((float(tri[:, 0].min()), float(tri[:, 2].min())), (float(tri[:, 0].max()), float(tri[:, 2].max()))))
    lists = {}
    for nm, b in entries(A["main"]).get("rScrList", []):
        q = os.path.join(d, base(nm) + ".rScrList")
        open(q, "wb").write(lp2nav.scrlist_add(b, sorted(names.items())))
        lists[base(nm) + ".rScrList"] = q
    put(A["main"], lists)
    put(A["main"], {names[29] + ".rAINavigationMeshList": files[0], names[30] + ".rAIWayPoint": files[1], names[31] + ".rIntelligenceBox": box}, add=True)
    log(f"navmesh packaged: {os.path.getsize(files[0]) // 1024} + {os.path.getsize(files[1]) // 1024} + {os.path.getsize(box) // 1024} KB")


def compile_project(game, folder, out_zip, work=None, log=print, library=None):
    p = lp2project.load(folder)
    bad = lp2project.check(folder)
    if bad:
        raise SystemExit(f"{folder}: " + "; ".join(bad))
    P = lambda rel: lp2project.path(folder, rel)
    info, env, stock_no = p["info"], p["environment"], p["base"].get("stock", 0)
    no_weather_volumes(p)
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
        nav = ensure_navmesh(folder, tag, library, log)
        radar = lp2radar.build(folder, p, log)
        if radar:
            off_mesh_warning(folder, p, radar["tris"], log)
            radar["boxes"] = lp2radar.zone_boxes(p, radar["tris"])
            y = radar["tris"][..., 1]
            radar["height"] = (float(y.min()) - 5000.0, float(y.max()) + 5000.0)
        else:
            log("radar: no navmesh, the radar stays blank (build one in the Navmesh window)")
        strip_base(A, stock, env, W, log, radar)
        add_weather(game, A, env, W, log)
        if nav:
            add_navmesh(A, tag, nav, folder, W, log)
        tmpl = {}
        os.makedirs(W("tmpl"), exist_ok=True)
        for k, cls, name in (("scr", "rModel", "online00"), ("scr", "rCollision", "atarionline00"),
                             ("scr", "rCollision", "tamaonline00"), ("v", "rHkCollision", "havonline00")):
            tmpl[name] = W("tmpl", name + "." + cls)
            open(tmpl[name], "wb").write(next(d for n, d in stock[k][cls] if base(n).lower() == name))

        stage = W("stage")
        shutil.rmtree(stage, ignore_errors=True)
        report(0.05, "stage model")
        if p["stage"].get("lp2_stage"):   # an LP2 map's stage, already in the stage format (lp2project import-lp2)
            models = [os.path.join(P(p["stage"]["lp2_stage"]), *STAGE_DIR.split("\\"), "online00.rModel")]
            log(f"stage model: LP2 online {p['stage'].get('lp2_map', '?')}")
            copy_lp2_stage(P(p["stage"]["lp2_stage"]), stage)
        else:
            models = [P(m) for m in p["stage"]["lp1_models"]]
            log("stage model: " + ", ".join(os.path.basename(m).split(".")[0] for m in models))
            tool("lp2stage.py", "--template", tmpl["online00"], "--out", stage, "--tex-dir", STAGE_DIR,
                 "--light", p["stage"].get("light_scale", 0.5), "--balance", p["stage"].get("light_balance", 1.0), *sum((["--empty", s] for s in STUBS), []), *models,
                 progress=(0.05, 0.55))
        geo = lp2pieces.load_geometry(P(p["geometry"]["file"])) if p.get("geometry") else {}
        if p.get("terrains"):   # terrain areas: built as pieces of the project's own, placed as copies
            import lp2terrain
            report(0.555, "terrain")
            geo = lp2terrain.add_copies(game, folder, p, geo, log)
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
        if lp2bake.settings(p)["source"] == "bake":   # our ray-traced light instead of the LP1 lightmap's
            report(0.57, "baking the lighting")
            dyn = None
            if pieces is not None and any(lp2pieces.dynamic_parts(geo)):
                dyn = lp2pieces.dynamic_points(pieces[0], pieces[1], geo, library, folder)
            lp2bake.bake_stage(os.path.join(stage, *STAGE_DIR.split("\\"), "online00.rModel"), folder, p, log, dyn)
        sky = env.get("skybox") or {"type": "map"}
        if sky.get("type") in ("stock", "panorama"):
            report(0.58, "sky")
            sky_sources(game, folder, p, sky, stage, A, log)
        build_scr(A["scr"], stage, A["scr"])
        # the stock map's water planes (effect models, its spots only) -> the stub; water is a project setting
        stub = os.path.join(stage, *STAGE_DIR.split("\\"), STUBS[-1] + ".rModel")
        put(A["main"], {"\\o00water.rModel": stub, "\\o00water2.rModel": stub})
        sz = lp2sound.project_zones(p, all_parts(p), volume_corners, volume_local)
        if sz:
            area = "aArea_ONLINE_%02d" % stock_no
            rev = next(d for n, d in stock["main"]["rPlanetReverb"] if base(n).lower() == area.lower())
            files = {}
            for i, (k, b) in enumerate(lp2sound.build(game, rev, area, *sz).items()):
                files[k] = W(f"sound{i}." + k.rsplit(".", 1)[1])
                open(files[k], "wb").write(b)
            put(A["main"], files)
            log(f"  sound: {len(sz[1])} reverb zone(s), presets " + ", ".join(sz[0]))

        for k, arc in A.items():  # own resource paths
            tool("arcsub.py", arc, arc + ".new", r"scr\\online\\online00\\", "scr\\\\Online\\\\%s\\\\" % tag)
            os.replace(arc + ".new", arc)

        log("collision + physics")
        report(0.6, "collision")
        files = {}
        kill = p.get("environment", {}).get("kill_floor")
        kills = [(volume_corners(v), volume_local(v)[1][1]) for v in all_parts(p) if volume_kill(v)]
        barriers = barrier_groups(p)
        for key, n in (("lp1_move", "atarionline00"), ("lp1_bullet", "tamaonline00")):
            out = W(n + ".rCollision")
            # cached by everything it's made from (the LP1 collision, the template, the stage's LP1 models and the
            # geometry edits for the pieces, the kill settings, the code)
            ck = collision_key(P(p["collision"][key]), tmpl[n], models if pieces else [], geo if pieces else {},
                               kill if key == "lp1_bullet" else None,
                               kills if key == "lp1_bullet" else [b["verts"] for b in barriers], library)
            hit = os.path.join(cache_dir("collision"), ck + ".rCollision")
            if os.path.exists(hit):
                shutil.copyfile(hit, out)
                log(f"  {n}: unchanged, from the cache")
                files[f"{tag}\\{n}.rCollision"] = out
                continue
            if pieces or ((kill is not None or kills) and key == "lp1_bullet") or (barriers and key == "lp1_move"):
                groups = lp2col.read_sbc1(open(P(p["collision"][key]), "rb").read())
                if pieces:
                    groups, (mv, dr, cp) = lp2pieces.apply_collision(groups, *pieces, geo)
                    extra = lp2pieces.foreign_collision(library, geo, key, folder)
                    groups += extra
                    if extra:
                        log(f"  {n}: {sum(len(g['tris']) for g in extra)} triangles from other maps' pieces")
                    log(f"  {n}: {mv} triangles moved, {dr} dropped, {cp} copied with the geometry")
                if kill is not None and key == "lp1_bullet":
                    # the game's kill floor: a 0x200 surface quad in the bullet collision (lp2col.kill_quad)
                    groups.append(lp2col.kill_quad(groups, float(kill)))
                    log(f"  {n}: kill floor at {float(kill) / 100:.1f} m")
                if barriers and key == "lp1_move":
                    groups += barriers
                    log(f"  {n}: {len(barriers)} barrier(s)")
                if kills and key == "lp1_bullet":
                    # kill volumes: the same kill surface over each box's top (the game only checks while falling)
                    for corners, top in kills:
                        groups.append(lp2col.kill_top(corners, top))
                    log(f"  {n}: {len(kills)} kill volume(s)")
                data, _ = lp2col.write_lp2(groups, open(tmpl[n], "rb").read())
                open(out, "wb").write(data)
            else:
                log("  " + tool("lp2col.py", P(p["collision"][key]), tmpl[n], out).strip().split(": ", 1)[1])
            cache_put(hit, out)
            files[f"{tag}\\{n}.rCollision"] = out
        if p["collision"].get("lp2_physics"):   # an LP2 map's own (map space, as the stage)
            shutil.copyfile(P(p["collision"]["lp2_physics"]), W("hav.rHkCollision"))
            log("  physics: the LP2 map's own" + (" (it keeps the original geometry)" if pieces else ""))
        elif not p["collision"].get("lp1_physics"):   # a new empty map: from the bullet collision
            log("  " + rebuild_physics(None, tmpl["havonline00"], W("hav.rHkCollision"), pieces, geo, library, folder,
                                       bullet=P(p["collision"]["lp1_bullet"])))
        elif pieces and (p["collision"].get("rebuild_physics") or p.get("terrains")):   # terrain: grenades land on it
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
                if (cls == "rScheduler" and ("_Light" in b or "_filter" in b.lower() or "_efc" in b.lower() or b == "online00_cam")) \
                        or cls == "rSceneBox2":
                    if cls == "rSceneBox2":   # the stock zones' fog, weather, field effects, wind, env textures
                        data = lp2scenebox.neutral(data, env.get("fog"))
                    open(os.path.join(li, b + "." + cls), "wb").write(data)
        json.dump(env["camera"] or camera(floor), open(W("cam.json"), "w"))
        bounds = f"{floor.lo[0] - 500:.0f},{floor.lo[2] - 500:.0f},{floor.hi[0] + 500:.0f},{floor.hi[2] + 500:.0f}"
        curves = ";".join(f"{c}:{csv(v[0])}/{csv(v[1])}" for c, v in lp2project.curves(env).items())
        light_env = {k: env.get(k) for k in ("sun_colour", "sky_colour", "ground_colour", "ambient", "scatter")}
        light_env["lights"] = p.get("lights") or []
        json.dump(light_env, open(W("light_env.json"), "w"))
        tool("lp2light.py", "--sun", csv(env["sun"]), "--tint", csv(env["tint"]), "--bounds", bounds, "--cam", W("cam.json"),
             "--sky", csv(env["sky"]), "--bloom", csv(env["bloom"]), "--curves", curves,
             *(["--keep-colours"] if env["colours"] == "stock" else []),
             *(["--keep-atmosphere"] if env["atmosphere"] == "stock" else []),
             *(["--water", env["water"]] if env["water"] is not None else []),
             "--weather", weather_rates(env),
             "--env", W("light_env.json"), li, lo)
        for f in os.listdir(lo):   # weather on in every zone, the no-weather volumes as zones
            if f.lower().endswith(".rscenebox2"):
                q = os.path.join(lo, f)
                data, nv, full = lp2weather.zones(open(q, "rb").read(), env.get("weather") or {})
                open(q, "wb").write(data)
                if full:
                    log(f"  {full} grid cells had no room for a no-weather volume")
        out = {f: os.path.join(lo, f) for f in os.listdir(lo)}
        put(A["main"], out)
        in_v = {(base(nm) + "." + cls).lower() for cls, items in stock["v"].items() for nm, _ in items}
        put(A["v"], {f: q for f, q in out.items() if f.lower() in in_v})

        preload = preload_arcs(game, ip_out)
        preload = sorted(set(preload) | set(script_preload(game, p)))
        log(f"  preload: {len(preload)} VS / weapon archives")
        manifest = dict(name=info["name"], base=0, number=0, size=info["size"], preload=preload)
        manifest.update(gravity_manifest(p))
        manifest.update(script_manifest(p, log))
        nz_file = os.path.join(folder, ".preview", "navzones.json")
        if os.path.isfile(nz_file):   # the bots' zones and links (lp2navmap): bots.cpp routes over them
            nz = json.load(open(nz_file))
            if nz.get("zones"):
                manifest["nav_zones"] = nz
                log(f"  bot zones: {len(nz['zones'])}, links {len(nz.get('links', []))}")
        if p.get("terrains"):   # damage-painted terrain layers: boxes over their cells
            import lp2terrain
            tdmg = lp2terrain.damage_volumes(folder, p, log)
            if tdmg:
                manifest["damage_volumes"] = manifest.get("damage_volumes", []) + tdmg
        json.dump(manifest, open(os.path.join(pkg, "map.json"), "w"), indent=1)
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
