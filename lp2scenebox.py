#!/usr/bin/env python3
"""rSceneBox2 ('SBL\\0' v0x103) reader / writer: the map's lighting zones and their fog.

  lp2scenebox.py FILE.rSceneBox2            print the layouts and their fog
  lp2scenebox.py --json FILE.rSceneBox2     the same as JSON

Layout (from the game's loader, DX9 rSceneBox2::vf9 0xfd27c0; every value 4 bytes unless noted):
  'SBL\\0', u32 0x103, u32 layout count
  vec3 max, vec3 min (12 B each), 32 x 32 grid cells x 16 u32 (zone, blend zone, 14-entry list),
  u32, u32 flag, u32 n + n+1 bytes (the field set name, NUL included; nothing when n = 0), u32 x 3, u32 x 2
  per layout (rSceneBox2::LayoutElement):
    u32 priority, u32 shape type, shape (2: 8 u32 + 3 f32; 4: 4 f; 8: 7 f; 0x10: 6 f; 0x20: 19 f)
    weather  u32 on, u32, u32
    field    u32 x 4 flags, u32, u32 n + n u32 (fields), u32 n + n u32 (e2d), u32 on, f32, vec3, f32
    effect   u32 on, u32, f32, f32
    fog      (CONTENTS_DATA_FOG) u32 mControlFlag, u32 mDistanceType, f32 mFogStart, f32 mFogEnd,
             64 B mDistanceCurve, vec4 mFogColor (16 B), 3 x 64 B mR/G/BCurve, f32 mFogBlendFrame,
             u32 mHeightType, f32 mHeightStart, f32 mHeightEnd, vec4 mHeightColor
    wind     u32 on, 128 B
    env      u32 on, u32 has texture [+ u32 size + NUL-terminated texture path], f32
    scheduler u32 on, u32, u32
The Filter schedulers (lp2light.py) can key the fog per zone over the match (stock 07 / 08 / 09); the
values here are what the zone starts with.
"""
import json, struct, sys

SHAPE_FLOATS = {2: (8, 3), 4: (0, 4), 8: (0, 7), 0x10: (0, 6), 0x20: (0, 19)}
FOG_FIELDS = ("mControlFlag", "mDistanceType", "mFogStart", "mFogEnd", "mDistanceCurve", "mFogColor",
              "mRCurve", "mGCurve", "mBCurve", "mFogBlendFrame", "mHeightType", "mHeightStart",
              "mHeightEnd", "mHeightColor")


class Reader:
    def __init__(self, b, at=0):
        self.b, self.at = b, at

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.at)[0]
        self.at += 4
        return v

    def f32(self, n=None):
        if n is None:
            v = struct.unpack_from("<f", self.b, self.at)[0]
            self.at += 4
            return v
        v = list(struct.unpack_from("<%df" % n, self.b, self.at))
        self.at += 4 * n
        return v

    def raw(self, n):
        v = self.b[self.at:self.at + n]
        self.at += n
        return v

    def cstr(self):
        end = self.b.index(b"\0", self.at)
        v = self.b[self.at:end].decode("latin-1")
        self.at = end + 1
        return v


def parse(b):
    """-> dict(header bytes end, layouts [dict(at_fog, fog {...}, priority, shape, ...)]), raising on a mismatch."""
    if b[:4] != b"SBL\0" or struct.unpack_from("<I", b, 4)[0] != 0x103:
        raise ValueError("not an rSceneBox2 v0x103")
    count = struct.unpack_from("<I", b, 8)[0]
    r = Reader(b, 12)
    out = {"max": r.f32(3), "min": r.f32(3)}
    r.at += 32 * 32 * 16 * 4
    r.u32(); r.u32()
    n = r.u32()
    out["name"] = r.raw(n + 1).rstrip(b"\0").decode("latin-1") if n else ""  # 0: no name bytes at all
    for _ in range(5):
        r.u32()
    out["at_layouts"] = r.at
    layouts = []
    for _ in range(count):
        L = {"at": r.at, "priority": r.u32(), "shape": r.u32()}
        if L["shape"] != 1:  # 1 = no shape data
            ints, floats = SHAPE_FLOATS[L["shape"]]
            L["shape_data"] = [r.u32() for _ in range(ints)] + r.f32(floats)
        L["weather"] = [r.u32() for _ in range(3)]
        flags = [r.u32() for _ in range(5)]
        fields = [r.u32() for _ in range(r.u32())]
        e2d = [r.u32() for _ in range(r.u32())]
        L["field"] = dict(flags=flags, fields=fields, e2d=e2d, on=r.u32(), a=r.f32(), v=r.f32(3), b=r.f32())
        L["effect"] = [r.u32(), r.u32(), r.f32(), r.f32()]
        L["at_fog"] = r.at
        fog = {"mControlFlag": r.u32(), "mDistanceType": r.u32(), "mFogStart": r.f32(), "mFogEnd": r.f32(),
               "mDistanceCurve": r.f32(16), "mFogColor": r.f32(4), "mRCurve": r.f32(16), "mGCurve": r.f32(16),
               "mBCurve": r.f32(16), "mFogBlendFrame": r.f32(), "mHeightType": r.u32(), "mHeightStart": r.f32(),
               "mHeightEnd": r.f32(), "mHeightColor": r.f32(4)}
        L["fog"] = fog
        L["wind_on"] = r.u32()
        L["wind"] = r.raw(128)
        env_on, has_tex = r.u32(), r.u32()
        if has_tex:
            r.u32()  # the path's buffer size
        L["env"] = {"on": env_on, "texture": r.cstr() if has_tex else None}
        L["env"]["value"] = r.f32()
        L["scheduler"] = [r.u32(), r.u32(), r.u32()]
        L["end"] = r.at
        layouts.append(L)
    if r.at != len(b):
        raise ValueError("parsed %d of %d bytes" % (r.at, len(b)))
    out["layouts"] = layouts
    return out


FOG_SIZE = 4 * 4 + 64 + 16 + 3 * 64 + 4 * 4 + 16


def pack_fog(fog):
    f = fog
    return (struct.pack("<IIff", int(f["mControlFlag"]), int(f["mDistanceType"]), f["mFogStart"], f["mFogEnd"])
            + struct.pack("<16f", *f["mDistanceCurve"]) + struct.pack("<4f", *f["mFogColor"])
            + struct.pack("<16f", *f["mRCurve"]) + struct.pack("<16f", *f["mGCurve"]) + struct.pack("<16f", *f["mBCurve"])
            + struct.pack("<fIff", f["mFogBlendFrame"], int(f["mHeightType"]), f["mHeightStart"], f["mHeightEnd"])
            + struct.pack("<4f", *f["mHeightColor"]))


def set_fog(b, fogs):
    """b with layout i's fog replaced by fogs[i] (a full fog dict; None keeps it). Sizes never change."""
    sb = parse(b)
    out = bytearray(b)
    for L, fog in zip(sb["layouts"], fogs):
        if fog is not None:
            out[L["at_fog"]:L["at_fog"] + FOG_SIZE] = pack_fog(fog)
    return bytes(out)


# a zone with nothing of the stock map's: no fog (unless given), weather, field / 2D effects (the field set's
# placed effects), wind or environment texture; its shape, priority, field flags and scheduler link stay
OFF_FOG = {"mControlFlag": 0, "mDistanceType": 0, "mFogStart": 0.0, "mFogEnd": 1.0, "mDistanceCurve": [0.0] * 16,
           "mFogColor": [0.5, 0.5, 0.5, 1.0], "mRCurve": [0.0] * 16, "mGCurve": [0.0] * 16, "mBCurve": [0.0] * 16,
           "mFogBlendFrame": 0.0, "mHeightType": 0, "mHeightStart": 0.0, "mHeightEnd": 1.0, "mHeightColor": [0.5, 0.5, 0.5, 1.0]}


# every stock map's distance and colour curves (two 8-value halves: 0 then 1s)
STOCK_CURVE = ([0.0] + [1.0] * 7) * 2


def from_project(p):
    """project.json environment.fog (the editor's Fog window: on, start, end (cm), colour, density, height_on,
    height_top, height_bottom (cm), height_colour, height_density) -> a fog dict. The colours' alpha is the
    strength (stock: 0 = none). Distance type 4 and blend frame 1 as most stock zones."""
    if not p:
        return None
    if any(k.startswith("m") for k in p):   # already the game's fields
        return p
    dist, low = bool(p.get("on")), bool(p.get("height_on"))
    if not (dist or low):
        return None
    c, hc = list(p.get("colour", [0.6, 0.65, 0.7]))[:3], list(p.get("height_colour", [0.6, 0.65, 0.7]))[:3]
    return {"mControlFlag": 1, "mDistanceType": 4, "mFogStart": float(p.get("start", 2000.0)),
            "mFogEnd": float(p.get("end", 30000.0)), "mDistanceCurve": STOCK_CURVE,
            "mFogColor": c + [float(p.get("density", 0.5)) if dist else 0.0],
            "mRCurve": STOCK_CURVE, "mGCurve": STOCK_CURVE, "mBCurve": STOCK_CURVE, "mFogBlendFrame": 1.0,
            "mHeightType": 1, "mHeightStart": float(p.get("height_top", 0.0)) if low else 100.0,
            "mHeightEnd": float(p.get("height_bottom", -1000.0)) if low else 0.0,
            "mHeightColor": hc + [float(p.get("height_density", 0.5)) if low else 0.0]}


def neutral(b, fog=None):
    """b with every layout neutral (above); fog: a fog dict for every layout (missing fields from OFF_FOG), or the
    project's environment.fog (from_project)"""
    sb = parse(b)
    f = dict(OFF_FOG, **(from_project(fog) or {}))
    out = bytearray(b[:sb["at_layouts"]])
    for L in sb["layouts"]:
        out += struct.pack("<II", L["priority"], L["shape"])
        if L["shape"] != 1:
            ints, floats = SHAPE_FLOATS[L["shape"]]
            out += struct.pack(f"<{ints}I{floats}f", *L["shape_data"])
        out += struct.pack("<3I", 0, 0, 0)
        F = L["field"]
        out += struct.pack("<5I", *F["flags"]) + struct.pack("<II", 0, 0)
        out += struct.pack("<If3ff", F["on"], F["a"], *F["v"], F["b"])
        out += struct.pack("<IIff", 0, L["effect"][1], L["effect"][2], L["effect"][3])
        out += pack_fog(f)
        out += struct.pack("<I", 0) + L["wind"]
        out += struct.pack("<IIf", 0, 0, L["env"]["value"])
        out += struct.pack("<3I", *L["scheduler"])
    parse(bytes(out))  # still a valid file
    return bytes(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    sb = parse(open(args[0], "rb").read())
    if "--json" in sys.argv:
        for L in sb["layouts"]:
            L.pop("at_fog")
        print(json.dumps(sb, indent=1))
        return
    print(sb["name"], "layouts", len(sb["layouts"]))
    for i, L in enumerate(sb["layouts"]):
        f = L["fog"]
        print(" %2d prio %d shape %#x fog on %d type %d %.0f..%.0f colour %s height type %d %.0f..%.0f %s" % (
            i, L["priority"], L["shape"], f["mControlFlag"], f["mDistanceType"], f["mFogStart"], f["mFogEnd"],
            [round(x, 3) for x in f["mFogColor"]], f["mHeightType"], f["mHeightStart"], f["mHeightEnd"],
            [round(x, 3) for x in f["mHeightColor"]]))


if __name__ == "__main__":
    main()
