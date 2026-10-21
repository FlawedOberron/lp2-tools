#!/usr/bin/env python3
"""Static daylight for a ported map: rewrite a stock area's light / filter rSchedulers and its rSceneBox2.

  lp2light.py --sun X,Y,Z [--tint R,G,B] [--bounds MINX,MINZ,MAXX,MAXZ] [--zone N] [--cam CAM.json] IN_DIR OUT_DIR

IN_DIR: the stock files as NAME.rScheduler (tool\\scheduler\\Light\\*_LightN_windows, Filter\\*_filterN_windows)
and NAME.rSceneBox2. Written to OUT_DIR under the same names.
--sun: direction towards the sun (Y up; e.g. from the baked vertex light). --tint: multiplies the sun colour.

rScheduler ('SDL\\0' v0x14): u16 track count at 6, u32 string table offset at 0x14, tracks x 24 B from 0x30:
  u8 kind (2 object, 5 pointer object, 6 int, 7 vector, 8 float, 9 bool), u8 value type (0x14 vec3,
  0x15 colour, 0x0c f32), u16 key count, u32 (not the owner: values follow their object track), u32 name (string table), u32 0,
  u32 key times offset (u32 each), u32 key values offset (16 B per vector key, 4 B per float key).
Stock online maps key a day / night cycle over the match (several keys per value); every key is set to the
first (day) one here, then:
  the directional sun (OBJ_Light mDir) and LightSpaceShadow mLightDir -> --sun; the other directional lights
  (HM_Light mDir) turn with the sun; the filter's scattering sun (mSunDir, the direction light travels) -> -sun;
  OBJ_Light mColor x --tint; spot lights (PL_SpotLight, placed for the stock map) mColor -> 0.
  Optional filter overrides: --sky (mpAreaLScattering mSunColor: the sky's tint), --bloom (mBloomColor),
  --curves (ColorCorrectFilter mToneCurveR/G/B, kind 14: 4 f32 curve points).
--cam: the start (intro) camera, event_LP2\\rt_online\\onlineNN_cam.rScheduler (EventMotionCamera): its
mOffsetPos (camera position) and mTrackTarget (look-at) keys <- {"cam": [[x, y, z], ...], "tgt": [...]},
one entry per stock key (online00: 4 keys over 90 frames).
rSceneBox2 ('SBL\\0'): 0x0C vec3 max, 0x18 vec3 min (x / z used), 0x24 a 32 x 32 grid of 64 B cells
(u32 zone, u32 blend zone, 14 x i32 list, -1 terminated) mapping the area to its lighting zones; every cell
-> --zone (default: the most common), bounds -> --bounds.
"""
import argparse, collections, json, os, struct
import numpy as np


def tracks(b):
    n, st = struct.unpack_from("<H", b, 6)[0], struct.unpack_from("<I", b, 0x14)[0]
    out = []
    for i in range(n):
        kind, vt, keys, parent, name, _z, t_off, v_off = struct.unpack_from("<BBHIIIII", b, 0x30 + 24 * i)
        out.append(dict(kind=kind, vt=vt, keys=keys, parent=parent, v=v_off,
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


def light(b, sun, tint):
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


def filt(b, sun, sky=None, bloom=None, curves=None):
    b = bytearray(b)
    for t in tracks(b):
        if t["kind"] == 14 and curves and t["name"] in curves:  # tone curve: 4 f32 points
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sun", required=True)
    ap.add_argument("--tint", default="1,1,1")
    ap.add_argument("--bounds")
    ap.add_argument("--zone", type=int)
    ap.add_argument("--cam")
    ap.add_argument("--sky", help="scattering sun colour R,G,B (sky tint; online00 day: 10,9.02,4 = yellow)")
    ap.add_argument("--bloom", help="bloom colour R,G,B")
    ap.add_argument("--curves", help="tone curves 'R:a,b,c,d;G:...;B:...' (4 points each; online00 grades green)")
    ap.add_argument("src")
    ap.add_argument("dst")
    a = ap.parse_args()
    sun = unit([float(x) for x in a.sun.split(",")])
    tint = np.array([float(x) for x in a.tint.split(",")])
    bounds = [float(x) for x in a.bounds.split(",")] if a.bounds else None
    rgb = lambda x: np.array([float(v) for v in x.split(",")]) if x else None
    sky, bloom = rgb(a.sky), rgb(a.bloom)
    curves = {f"mToneCurve{c.split(':')[0]}": [float(v) for v in c.split(':')[1].split(",")] for c in a.curves.split(";")} if a.curves else None
    os.makedirs(a.dst, exist_ok=True)
    for f in sorted(os.listdir(a.src)):
        b = open(os.path.join(a.src, f), "rb").read()
        low = f.lower()
        if low.endswith(".rscheduler") and "_light" in low:
            out, changed = light(b, sun, tint)
            note = f"{sum(changed.values())} vector tracks"
        elif low.endswith(".rscheduler") and "_filter" in low:
            out, note = filt(b, sun, sky, bloom, curves), "filter"
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
