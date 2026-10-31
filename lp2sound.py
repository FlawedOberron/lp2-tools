#!/usr/bin/env python3
"""Sound zones: reverb per area of a map, as the stock maps' interiors (no xlive mod: the game's own files).

  lp2sound.py presets GAME          (re)writes sound_presets.json from the stock online maps' reverb files
  lp2sound.py dump FILE             a zone file (rSoundSeGenerator) or reverb file (rPlanetReverb), readable

The area load reads Sound\\reverb\\<area> (rPlanetReverb: presets, each 4 cReverbParam I3DL2 effects) and
Sound\\seg\\reverb\\<area>_rv (rSoundSeGenerator "SEG\\0" v8: u16 count at 6, u16 record size 0x2c0 at 10, records
from 0x10). A record is the in-memory LayoutInfo from its +0x90 (DX11 FUN_00fe7a00 copies it):
  +0x00 u32 SHAPE (1: four corners + a height)   +0x04 u32 SHUTOUT ID
  +0x10 / 0x20 / 0x30 / 0x40 SetPos0-3 (vec3, the floor's corners; stock order: (B-A) x (C-B) has +y)
  +0x50 Height0 (up from the floor), Height1-3, +0x60 Radius   +0x64 CHECK   +0x74 SUCCESS (8: set the reverb)
  +0x7c / 0xc0 / 0x104 / 0x148 SE / SE out / stream / stream out names (64 chars, "NONE")
  +0x290 s32 SET REVERB (the preset entered)   +0x294 s32 SET REVERBOUT (on leaving; -1 none)
  +0x29c GENERATOR NO (1 on the stock maps' map-wide zone)   +0x2a0 SHUTOUT VOLUME   +0x2ac u16 UNIQUE ID
Stock maps (Frozen Wasteland): rooms set preset 1 and back to 0 on leaving, then a map-wide zone sets 0.
"""
import json, os, struct, sys

import xfsedit

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(HERE, "sound_presets.json")
REC = 0x2C0
BIG = 1e6   # the map-wide zone's half width (cm)


def presets():
    """{key: {"name": map preset comment, "params": [4 cReverbParam field dicts]}}; key "00", "02_inside", ..."""
    return json.load(open(PRESETS))


def key_of(comment):
    return comment.replace("aArea_ONLINE_", "").lower()


def make_presets(game):
    import arcx
    d = os.path.join(game, "nativePC", "arcXmlTmpPC")
    types, out = arcx.load_types(), {}
    import zlib
    for f in sorted(os.listdir(d)):
        if not (f.startswith("aArea_ONLINE_") and f.endswith(".arc")):
            continue
        b = open(os.path.join(d, f), "rb").read()
        for n, h, cs, ds, fl, o in arcx.entries(b):
            if types.get(h) == "rPlanetReverb":
                x = xfsedit.parse(b[o:o + cs] if cs == ds else zlib.decompress(b[o:o + cs]))
                for e in x["root"]["mReverb"][0]["mpArray"]:
                    params = [{k: v[0] for k, v in q.items() if not k.startswith("_")} for q in e["mReverbParam"]]
                    out[key_of(e["Comment"][0])] = {"name": e["Comment"][0], "params": params}
    json.dump(out, open(PRESETS, "w"), indent=1)
    return out


def reverb_file(stock, keys):
    """the stock reverb file with presets `keys` in that order (index = mUniqueID = the zones' SET REVERB)"""
    x = xfsedit.parse(stock)
    arr = x["root"]["mReverb"][0]
    tmpl = arr["mpArray"][0]
    table = presets()
    items = []
    for i, k in enumerate(keys):
        e = json.loads(json.dumps(tmpl))
        e["mUniqueID"], e["Comment"] = [i], [table[k]["name"]]
        for q, p in zip(e["mReverbParam"], table[k]["params"]):
            for f, v in p.items():
                q[f] = [v]
        items.append(e)
    arr["mpArray"] = items
    n = [0]
    def ids(o):   # object ids in file order
        o["_id"] = n[0]
        n[0] += 1
        for name, t, _s in x["classes"][o["_cls"]]:
            if t in (1, 2):
                for c in o[name]:
                    ids(c)
    ids(x["root"])
    return xfsedit.write(x)


def zone_record(tmpl, corners, floor, height, reverb, out, uid, generator=0):
    r = bytearray(tmpl)
    pts = corners
    a, b, c = pts[0], pts[1], pts[2]
    if (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1]) < 0:   # the stock winding
        pts = pts[::-1]
    for k, (x, z) in enumerate(pts):
        struct.pack_into("<4f", r, 0x10 + 16 * k, x, floor, z, 0.0)
    struct.pack_into("<f", r, 0x50, height)
    struct.pack_into("<I", r, 0x74, 8)
    for o in (0x7C, 0xC0, 0x104, 0x148):
        r[o:o + 0x40] = b"NONE".ljust(0x40, b"\0")
    struct.pack_into("<iiI", r, 0x290, reverb, out, 0)
    struct.pack_into("<I", r, 0x29C, generator)
    struct.pack_into("<H", r, 0x2AC, uid)
    return bytes(r)


def zone_file(stock_rv, tmpl_rec, zones, default):
    """zones: [(corners [(x, z)] * 4, floor y, height, preset index)]; then the map-wide zone setting `default`"""
    recs = [zone_record(tmpl_rec, c, f, h, i, default, n) for n, (c, f, h, i) in enumerate(zones)]
    w = BIG
    recs.append(zone_record(tmpl_rec, [(-w, -w), (-w, w), (w, w), (w, -w)], -w, 2 * w, default, -1, len(zones), 1))
    head = bytearray(stock_rv[:0x10])
    struct.pack_into("<HH", head, 6, len(recs), 0)
    struct.pack_into("<H", head, 10, REC)
    return bytes(head) + b"".join(recs)


def stock_entry(game, arc, cls, name):
    import arcx, zlib
    b, types = open(os.path.join(game, "nativePC", "arcXmlTmpPC", arc), "rb").read(), arcx.load_types()
    for n, h, cs, ds, fl, o in arcx.entries(b):
        if types.get(h) == cls and n.lower() == name.lower():
            return b[o:o + cs] if cs == ds else zlib.decompress(b[o:o + cs])
    raise KeyError(name)


def project_zones(p, parts, corners, local):
    """the project's sound volumes (volume "sound": {"reverb": preset key}) and the map's preset (environment
    "sound": {"reverb"}, else the base map's) -> preset keys (the map's first), zones; None: nothing to change"""
    default = (p.get("environment", {}).get("sound") or {}).get("reverb")
    vols = [v for v in parts if (v.get("sound") or {}).get("reverb")]
    if not vols and not default:
        return None
    table = presets()
    keys = [default if default in table else "%02d" % p["base"].get("stock", 0)]
    zones = []
    for v in vols:
        k = v["sound"]["reverb"]
        if k not in table:
            raise SystemExit(f"sound volume: unknown reverb preset {k!r} (sound_presets.json)")
        if k not in keys:
            keys.append(k)
        lo, hi = local(v)
        zones.append((corners(v), lo[1], hi[1] - lo[1], keys.index(k)))
    return keys, zones


def build(game, stock, area, keys, zones):
    """-> {arc entry NAME.CLASS: data} for the package's main arc (area: "aArea_ONLINE_00")"""
    rv = stock_entry(game, area + ".arc", "rSoundSeGenerator", f"Sound\\seg\\reverb\\{area}_rv")
    tmpl = stock_entry(game, "aArea_ONLINE_15.arc", "rSoundSeGenerator", "Sound\\seg\\reverb\\aArea_ONLINE_15_rv")
    rec = tmpl[0x10:0x10 + REC]
    return {f"Sound\\reverb\\{area}.rPlanetReverb": reverb_file(stock, keys),
            f"Sound\\seg\\reverb\\{area}_rv.rSoundSeGenerator": zone_file(rv, rec, zones, 0)}


def dump(path):
    b = open(path, "rb").read()
    if b[:4] == b"XFS\0":
        for e in xfsedit.parse(b)["root"]["mReverb"][0]["mpArray"]:
            p = e["mReverbParam"][0]
            print(e["mUniqueID"][0], e["Comment"][0], "room", p["Room"][0], "decay", round(p["DecayTime"][0], 2),
                  "reverb", p["Reverb"][0])
        return
    n, sz = struct.unpack_from("<H", b, 6)[0], struct.unpack_from("<H", b, 10)[0]
    for i in range(n):
        r = 0x10 + i * sz
        f = lambda o: struct.unpack_from("<f", b, r + o)[0]
        pts = [(round(f(0x10 + 16 * k)), round(f(0x18 + 16 * k))) for k in range(4)]
        print(i, "floor", round(f(0x14)), "height", round(f(0x50)), pts, "reverb / out",
              struct.unpack_from("<ii", b, r + 0x290), "uid", struct.unpack_from("<H", b, r + 0x2AC)[0])


if __name__ == "__main__":
    if sys.argv[1:2] == ["presets"]:
        print(len(make_presets(sys.argv[2])), "presets ->", PRESETS)
    elif sys.argv[1:2] == ["dump"]:
        dump(sys.argv[2])
    else:
        print(__doc__)
