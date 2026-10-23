#!/usr/bin/env python3
"""Static daylight for a ported map: rewrite a stock area's light / filter rSchedulers and its rSceneBox2.

  lp2light.py --sun X,Y,Z [--tint R,G,B] [--bounds MINX,MINZ,MAXX,MAXZ] [--zone N] [--cam CAM.json] IN_DIR OUT_DIR

IN_DIR: the stock files as NAME.rScheduler (tool\\scheduler\\Light\\*_LightN_windows, Filter\\*_filterN_windows)
and NAME.rSceneBox2. Written to OUT_DIR under the same names.
--sun: direction towards the sun (Y up; e.g. from the baked vertex light). --tint: multiplies the sun colour.
The sun (OBJ_Light), ambient (mpAmbientLight) and hemisphere (HemiSphereLight) colours become grey of the same
brightness first (online00: yellow sun + cyan fill read as green); --keep-colours keeps them.

rScheduler ('SDL\\0' v0x14): u16 track count at 6, u32 frames at 0x0C, u32 string table offset at 0x14, tracks x 24 B
  from 0x18 (track 0 = the root, kind 1): u8 kind (1 root, 2 object, 3 resource, 5 pointer object, 6 int,
  7 vector, 8 float, 9 bool), u8 value type (0x14 vec3, 0x15 colour, 0x0c f32), u16 key count, u32 parent
  (a value's object track; objects: 6), u32 name (string table), u32 class (objects: DTI hash, else 0),
  u32 key times offset (u32 each: interpolation << 24 | frame), u32 key values offset (16 B per vector key,
  4 B per float key). Offsets are absolute: tracks, then key data, then the string table.
Stock online maps key a day / night cycle over the match (several keys per value); every key is set to the
first (day) one here, then:
  the directional sun (OBJ_Light mDir) and LightSpaceShadow mLightDir -> --sun; the other directional lights
  (HM_Light mDir) turn with the sun; the filter's scattering sun (mSunDir, the direction light travels) -> -sun;
  OBJ_Light mColor x --tint; spot lights (PL_SpotLight, placed for the stock map) mColor -> 0.
  The atmosphere (mpAreaLScattering Rayleigh / Mie / density) -> online01's clear sky (--keep-atmosphere keeps it).
  Optional filter overrides: --sky (mpAreaLScattering mSunColor: the sky's tint), --bloom (mBloomColor),
  --curves (ColorCorrectFilter mToneCurveR/G/B, kind 14: 4 f32 curve points).
Effect schedulers (tool\\scheduler\\Effect\\*_EfcN_*): weather (mWeatherRate, int; online00 50 = its falling
ash) off; the water plane (mWaterExist, bool + mWaterHeight, f32 cm) off, or on at --water; 4 B per key.
--cam: the start (intro) camera, event_LP2\\rt_online\\onlineNN_cam.rScheduler (EventMotionCamera): its
mOffsetPos (camera position) and mTrackTarget (look-at) keys <- {"cam": [[x, y, z], ...], "tgt": [...]},
one entry per stock key (online00: 4 keys over 90 frames).
rSceneBox2 ('SBL\\0'): 0x0C vec3 max, 0x18 vec3 min (x / z used), 0x24 a 32 x 32 grid of 64 B cells
(u32 zone, u32 blend zone, 14 x i32 list, -1 terminated) mapping the area to its lighting zones; every cell
-> --zone (default: the most common), bounds -> --bounds.
"""
import argparse, collections, json, os, struct, sys
import numpy as np


def tracks(b):
    n, st = struct.unpack_from("<H", b, 6)[0], struct.unpack_from("<I", b, 0x14)[0]
    out = []
    for i in range(n):
        kind, vt, keys, parent, name, dti, t_off, v_off = struct.unpack_from("<BBHIIIII", b, 0x18 + 24 * i)
        out.append(dict(kind=kind, vt=vt, keys=keys, parent=parent, v=v_off, t=t_off, dti=dti, at=0x18 + 24 * i,
                        name=b[st + name:b.index(b"\0", st + name)].decode("latin-1")))
    obj = None
    for t in out:  # the object a value belongs to: the last object track before it
        if t["kind"] in (2, 3, 5):
            obj = t["name"]
        t["obj"] = obj
    return out


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def rotation(a, b):
    """the rotation taking unit vector a to b."""
    a, b = unit(a), unit(b)
    v, c = np.cross(a, b), float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def vec(b, t, j=0):
    return np.array(struct.unpack_from("<3f", b, t["v"] + 16 * j))


def put_all(b, t, value):
    for j in range(t["keys"]):
        struct.pack_into("<3f", b, t["v"] + 16 * j, *map(float, value))


NEUTRAL = {("OBJ_Light", "mColor"), ("HemiSphereLight", "mColor"), ("HemiSphereLight", "mRevColor"),
           ("mpAmbientLight", "mColor")}


def grey(c):
    """The same brightness without the hue (Rec. 709 luminance)."""
    return np.full(3, 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])


def neutral(b):
    """Sun, ambient and hemisphere colours -> grey (online00's: yellow sun + cyan fill = a green cast)."""
    b = bytearray(b)
    done = []
    for t in tracks(b):
        if t["kind"] == 7 and t["keys"] and (t["obj"], t["name"]) in NEUTRAL:
            for j in range(t["keys"]):
                struct.pack_into("<3f", b, t["v"] + 16 * j, *map(float, grey(vec(b, t, j))))
            done.append(f"{t['obj']}.{t['name']}")
    return bytes(b), done


def light(b, sun, tint, keep_colours=False, colours=None):
    """colours: {(object, track): absolute RGB} (the editor's sun / sky light / ambient), over the grey or stock ones"""
    colours = colours or {}
    if not keep_colours:
        b = neutral(b)[0]
    b = bytearray(b)
    T = tracks(b)
    sun_track = next(t for t in T if t["obj"] == "OBJ_Light" and t["name"] == "mDir")
    R = rotation(vec(b, sun_track), sun)
    changed = collections.Counter()
    for t in T:
        if t["keys"] < 1:
            continue
        if t["kind"] == 7:  # vectors / colours: day value everywhere
            first = vec(b, t)
            if t["obj"] == "OBJ_Light" and t["name"] == "mDir" or t["name"] == "mLightDir":
                first = sun
            elif t["obj"] == "HM_Light" and t["name"] == "mDir":
                first = R @ first
            elif (t["obj"], t["name"]) in colours:
                first = np.asarray(colours[(t["obj"], t["name"])], float)
            elif t["obj"] == "OBJ_Light" and t["name"] == "mColor":
                first = first * tint
            elif t["obj"] == "PL_SpotLight" and t["name"] == "mColor":
                first = np.zeros(3)
            put_all(b, t, first)
            changed[f"{t['obj']}.{t['name']}"] += 1
        elif t["kind"] == 8 and t["keys"] > 1:  # floats
            f = struct.unpack_from("<f", b, t["v"])[0]
            for j in range(t["keys"]):
                struct.pack_into("<f", b, t["v"] + 4 * j, f)
    return bytes(b), changed


# Atmosphere (mpAreaLScattering) from stock online01's day: a clear blue sky. online00's (Mie 100, density 0.7,
# blue scattered least) is a thick haze that, over a big ported map, tints the whole frame (sky and characters) green.
SCATTER = {"mRaylieghScattering": (17.0, 14.8, 13.9), "mMeiScattering": (2.94, 2.95, 3.0),
           "mMeiDirective": -0.1, "mDensity": 0.53}


def filt(b, sun, sky=None, bloom=None, curves=None, scatter=SCATTER):
    b = bytearray(b)
    for t in tracks(b):
        if t["obj"] == "mpAreaLScattering" and scatter and t["name"] in scatter and t["keys"]:
            v = scatter[t["name"]]
            for j in range(t["keys"]):
                if t["kind"] == 7:
                    struct.pack_into("<3f", b, t["v"] + 16 * j, *v)
                else:
                    struct.pack_into("<f", b, t["v"] + 4 * j, v)
        elif t["kind"] == 14 and curves and t["name"] in curves:  # tone curve: 4 f32 points
            struct.pack_into("<4f", b, t["v"], *curves[t["name"]])
        elif t["kind"] == 7 and t["keys"] >= 1:
            value = vec(b, t)
            if t["name"] == "mSunDir":
                value = -sun
            elif t["name"] == "mSunColor" and sky is not None:
                value = sky
            elif t["name"] == "mBloomColor" and bloom is not None:
                value = bloom
            put_all(b, t, value)
        elif t["kind"] == 8 and t["keys"] > 1:
            f = struct.unpack_from("<f", b, t["v"])[0]
            for j in range(t["keys"]):
                struct.pack_into("<f", b, t["v"] + 4 * j, f)
    return bytes(b)


def scenebox(b, bounds, zone):
    b = bytearray(b)
    assert b[:4] == b"SBL\0"
    cells = [struct.unpack_from("<I", b, 0x24 + 64 * i)[0] for i in range(1024)]
    if zone is None:
        zone = collections.Counter(cells).most_common(1)[0][0]
    for i in range(1024):
        struct.pack_into("<2I14i", b, 0x24 + 64 * i, zone, 0, *[-1] * 14)
    if bounds:
        x0, z0, x1, z1 = bounds
        y = struct.unpack_from("<f", b, 0x10)[0]
        struct.pack_into("<3f3f", b, 0x0C, x1, y, z1, x0, y, z0)
    return bytes(b), zone


def camera(b, cam):
    b = bytearray(b)
    for t in tracks(b):
        want = {"mOffsetPos": cam["cam"], "mTrackTarget": cam["tgt"]}.get(t["name"])
        if want and t["obj"] == "EventMotionCamera":
            if len(want) != t["keys"]:
                raise SystemExit(f"{t['name']} has {t['keys']} keys, CAM.json gives {len(want)}")
            for j, v in enumerate(want):
                struct.pack_into("<3f", b, t["v"] + 16 * j, *map(float, v))
    return bytes(b)


def effects(b, water=None):
    """No weather (online00's falling ash): mWeatherRate keys -> 0. The water plane (mWaterExist) is off, or on
    at height water (cm, mWaterHeight): below it players count as underwater."""
    b = bytearray(b)
    done = []
    for t in tracks(b):
        if t["name"] in ("mWeatherRate", "mWaterExist", "mWaterHeight") and t["keys"]:
            for j in range(t["keys"]):
                if t["name"] == "mWaterHeight":
                    struct.pack_into("<f", b, t["v"] + 4 * j, float(water or 0))
                else:
                    struct.pack_into("<I", b, t["v"] + 4 * j, int(t["name"] == "mWaterExist" and water is not None))
            done.append(t["name"])
    return bytes(b), done


# ---------------------------------------------------------------- placed lights: new scheduler objects
# Field lists as stock maps write them (online06 PointLight, online07 SpotLight): (kind, value type, name, default).
# Kinds 6 int / 9 bool keep time word 0, 7 vector / 8 float 0x03000000 (one key at frame 0).
# mGroup 0x2000 = the sun's group (stage models draw with mLightGroup 1, lit by it); mStart / mEnd: full light to
# that distance, none past mEnd (cm); spot mCone: the cone's full angle, mSpread: its soft edge (degrees).
LIGHT_CLASSES = {
    "point": ("PointLight", 0x49A43F8E, [
        (6, 6, "mGroup", 0x2000), (6, 6, "mAttr", 74), (7, 20, "mColor", None), (8, 12, "mBalance", 0.0),
        (8, 12, "ShadowGroup0", 1.0), (8, 12, "ShadowGroup1", 0.0), (7, 20, "mPos", None), (8, 12, "mStart", None),
        (8, 12, "mEnd", None), (9, 3, "mPS3Mode", 1)]),
    "spot": ("SpotLight", 0x6A2EC243, [
        (6, 6, "mGroup", 0x2000), (6, 6, "mAttr", 74), (6, 6, "mPriority", 0), (7, 20, "mColor", None),
        (8, 12, "mBalance", 0.0), (8, 12, "ShadowGroup0", 1.0), (8, 12, "ShadowGroup1", 0.0), (7, 20, "mPos", None),
        (7, 20, "mDir", None), (7, 20, "mTargetPos", (0.0, 0.0, 1.0)), (8, 12, "mStart", None), (8, 12, "mEnd", None),
        (8, 12, "mCone", None), (8, 12, "mSpread", None), (9, 3, "mPS3Mode", 1)]),
}
OBJECT_PARENT = 6   # what stock object tracks hold in the parent word


def light_values(L):
    """an editor light {type, pos, dir, colour, brightness, start, end, cone, spread} -> {field: value}"""
    c = np.asarray(L.get("colour", [1, 1, 1]), float) * float(L.get("brightness", 2.0))
    v = {"mColor": c, "mPos": L["pos"], "mStart": float(L.get("start", 100.0)), "mEnd": float(L.get("end", 1000.0))}
    if L["type"] == "spot":
        v.update(mDir=unit(L.get("dir", [0, -1, 0])), mCone=float(L.get("cone", 60.0)), mSpread=float(L.get("spread", 10.0)))
    return v


def add_objects(b, objs):
    """append objects to a scheduler: objs [(name, class hash, [(kind, value type, field, value)])].
    The track table grows (data offsets move by a multiple of 16, keeping vector keys aligned), the new keys go after
    the old ones and new names at the end of the string table."""
    n, st = struct.unpack_from("<H", b, 6)[0], struct.unpack_from("<I", b, 0x14)[0]
    table_end = 0x18 + 24 * n
    rows = [bytearray(b[0x18 + 24 * i:0x18 + 24 * i + 24]) for i in range(n)]
    data, strings = bytearray(b[table_end:st]), bytearray(b[st:])
    names = {}
    o = 0
    while o < len(strings):
        e = strings.index(b"\0", o)
        names.setdefault(strings[o:e].decode("latin-1"), o)
        o = e + 1

    def name_off(s):
        if s not in names:
            names[s] = len(strings)
            strings.extend(s.encode("latin-1") + b"\0")
        return names[s]

    new_rows, new_data = [], bytearray()
    for name, dti, fields in objs:
        new_rows.append([2, 0, 0, OBJECT_PARENT, name_off(name), dti, 0, 0])
        obj_index = n + len(new_rows) - 1
        for kind, vt, field, value in fields:
            while len(new_data) % 16:
                new_data.append(0)
            t_at = len(new_data)
            new_data += struct.pack("<I", 0x03000000 if kind in (7, 8) else 0)
            while len(new_data) % 16:
                new_data.append(0)
            v_at = len(new_data)
            if kind == 7:
                new_data += struct.pack("<4f", *map(float, value), 0.0)
            elif kind == 8:
                new_data += struct.pack("<f", float(value))
            else:
                new_data += struct.pack("<I", int(value))
            new_rows.append([kind, vt, 1, obj_index, name_off(field), 0, t_at, v_at])
    total = n + len(new_rows)
    shift = -(-(24 * total - 24 * n) // 16) * 16   # the table grows; data moves by a multiple of 16
    data_at = table_end + shift
    for r in rows:
        kind = r[0]
        to, vo = struct.unpack_from("<II", r, 16)
        if to:
            struct.pack_into("<I", r, 16, to + shift)
        if vo:
            struct.pack_into("<I", r, 20, vo + shift)
    pad = shift - 24 * (total - n)
    base = data_at + len(data)
    base += -base % 16
    out = bytearray(b[:0x18])
    for r in rows:
        out += r
    for k, vt, keys, par, nm, dti, to, vo in new_rows:
        out += struct.pack("<BBHIIIII", k, vt, keys, par, nm, dti, to + base if keys else 0, vo + base if keys else 0)
    out += bytes(pad)
    out += data
    out += bytes(base - len(out))
    out += new_data
    out += bytes(-len(out) % 4)
    struct.pack_into("<H", out, 6, total)
    struct.pack_into("<I", out, 0x14, len(out))
    out += strings
    return bytes(out)


def add_lights(b, lights):
    objs = []
    for L in lights:
        cls, dti, fields = LIGHT_CLASSES[L["type"]]
        vals = light_values(L)
        objs.append((cls, dti, [(k, vt, f, vals.get(f, d)) for k, vt, f, d in fields]))
    return add_objects(b, objs)


def presets(game):
    """every stock online map's day light and atmosphere (key 0 of Light0 / Filter0) -> {map number: {...}}"""
    import glob
    import lp2mapc
    keys = {("OBJ_Light", "mDir"): "sun", ("OBJ_Light", "mColor"): "sun_colour",
            ("HemiSphereLight", "mColor"): "sky_colour", ("HemiSphereLight", "mRevColor"): "ground_colour",
            ("mpAmbientLight", "mColor"): "ambient", ("BloomFilter", "mBloomColor"): "bloom"}
    scatter = {"mRaylieghScattering", "mMeiScattering", "mMeiDirective", "mDensity", "mSunColor"}
    out = {}
    for arc in sorted(glob.glob(os.path.join(game, "nativePC", "arcXmlTmpPC", "aArea_ONLINE_*.arc"))):
        num = os.path.basename(arc)[13:15]
        d = {"scatter": {}}
        for nm, b in lp2mapc.entries(arc).get("rScheduler", []):
            bn = lp2mapc.base(nm).lower()
            if not (bn.endswith("_light0_windows") or bn.endswith("_filter0_windows")):
                continue
            for t in tracks(b):
                if not t["keys"] or t["kind"] not in (7, 8):
                    continue
                v = list(struct.unpack_from("<3f", b, t["v"])) if t["kind"] == 7 else struct.unpack_from("<f", b, t["v"])[0]
                k = keys.get((t["obj"], t["name"]))
                if k and k not in d:
                    d[k] = [round(x, 4) for x in v] if isinstance(v, list) else v
                elif t["obj"] == "mpAreaLScattering" and t["name"] in scatter:
                    d["scatter"].setdefault(t["name"], [round(x, 4) for x in v] if isinstance(v, list) else round(v, 4))
        if not d["scatter"]:
            d.pop("scatter")
        out[num] = d
    return out


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "presets":
        ap = argparse.ArgumentParser(prog="lp2light.py presets")
        ap.add_argument("cmd")
        ap.add_argument("--game", required=True)
        ap.add_argument("out")
        a = ap.parse_args()
        json.dump(presets(a.game), open(a.out, "w"), indent=1)
        print(f"wrote {a.out}")
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sun", required=True)
    ap.add_argument("--tint", default="1,1,1")
    ap.add_argument("--keep-colours", action="store_true", help="keep the stock sun / ambient hues (default: grey)")
    ap.add_argument("--bounds")
    ap.add_argument("--zone", type=int)
    ap.add_argument("--cam")
    ap.add_argument("--sky", help="scattering sun colour R,G,B (sky tint; online00 day: 10,9.02,4 = yellow)")
    ap.add_argument("--bloom", help="bloom colour R,G,B")
    ap.add_argument("--keep-atmosphere", action="store_true", help="keep the stock scattering (default: online01's clear sky)")
    ap.add_argument("--curves", help="tone curves 'R:a,b,c,d;G:...;B:...' (4 points each; online00 grades green)")
    ap.add_argument("--water", type=float, help="water plane height in cm (default: no water)")
    ap.add_argument("--env", help="JSON: sun_colour, sky_colour, ground_colour, ambient (absolute RGB), scatter "
                    "{mpAreaLScattering track: value}, lights [{type point | spot, pos, colour, brightness, ...}]")
    ap.add_argument("src")
    ap.add_argument("dst")
    a = ap.parse_args()
    sun = unit([float(x) for x in a.sun.split(",")])
    tint = np.array([float(x) for x in a.tint.split(",")])
    bounds = [float(x) for x in a.bounds.split(",")] if a.bounds else None
    rgb = lambda x: np.array([float(v) for v in x.split(",")]) if x else None
    sky, bloom = rgb(a.sky), rgb(a.bloom)
    curves = {f"mToneCurve{c.split(':')[0]}": [float(v) for v in c.split(':')[1].split(",")] for c in a.curves.split(";")} if a.curves else None
    env = json.load(open(a.env)) if a.env else {}
    colours = {k: env[n] for k, n in ((("OBJ_Light", "mColor"), "sun_colour"), (("HemiSphereLight", "mColor"), "sky_colour"),
                                       (("HemiSphereLight", "mRevColor"), "ground_colour"),
                                       (("mpAmbientLight", "mColor"), "ambient")) if env.get(n) is not None}
    scatter = None if a.keep_atmosphere else {**SCATTER, **{k: tuple(v) if isinstance(v, list) else v
                                                             for k, v in (env.get("scatter") or {}).items() if k != "mSunColor"}}
    if (env.get("scatter") or {}).get("mSunColor"):   # a preset's sky colour wins over --sky
        sky = np.array(env["scatter"]["mSunColor"], float)
    lights = env.get("lights") or []
    os.makedirs(a.dst, exist_ok=True)
    for f in sorted(os.listdir(a.src)):
        b = open(os.path.join(a.src, f), "rb").read()
        low = f.lower()
        if low.endswith(".rscheduler") and "_light" in low:
            out, changed = light(b, sun, tint, a.keep_colours, colours)
            note = f"{sum(changed.values())} vector tracks"
            if lights:
                out = add_lights(out, lights)
                note += f", {len(lights)} placed lights"
        elif low.endswith(".rscheduler") and "_filter" in low:
            out, note = filt(b, sun, sky, bloom, curves, scatter), "filter"
        elif low.endswith(".rscheduler") and "_efc" in low:
            out, done = effects(b, a.water)
            note = "effects: " + (", ".join(done) + (f" (water at {a.water:g})" if a.water is not None else " off") if done else "nothing to change")
        elif low.endswith("_cam.rscheduler"):
            if not a.cam:
                continue
            out, note = camera(b, json.load(open(a.cam))), "start camera"
        elif low.endswith(".rscenebox2"):
            out, zone = scenebox(b, bounds, a.zone)
            note = f"zone {zone} everywhere"
        else:
            continue
        open(os.path.join(a.dst, f), "wb").write(out)
        print(f"{f}: {note}")


if __name__ == "__main__":
    main()
