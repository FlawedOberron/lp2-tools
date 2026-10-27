#!/usr/bin/env python3
"""Weather for a custom map (project.json environment.weather, the editor's Fog and weather window):

  environment.weather = {"type": "rain" | "rain_heavy" | "snow" | "ash", "amount": 0..100,
                         "volumes": [{"pos": [x, y, z], "size": [x, y, z]}, ...]}   (cm; volumes: no weather)

How the game draws it (from the stock maps):
  - the scenery list (rScrList) has a type 16 entry naming the weather's effect list (mPara1: a layer slot;
    underwater is slot 6); its textures / models / sub-lists are named inside it as path strings
  - every SceneBox zone has weather [on, amount 0..100, kind]; stock interiors are [1, 0, 0] at priority 7 under
    the whole-map zone (priority 15): no weather inside
  - the effect scheduler's mWeatherRate (int) is the weather's strength (stock 0 / 35 / 50; the match's Weather
    rule may override it)
The effect lists come from the stock map that has them (an explicit choice: the one thing a custom map takes from
another map). One SceneBox for every layout: weather is the same on all four.

  lp2weather.py deps --game GAME TYPE      list the resources a weather type needs
"""
import argparse, os, re, struct, sys, zlib

import arcx, xfsedit

TYPES = arcx.load_types()
# type -> (stock map, effect list, scenery list slot, zone kind, label)
PRESETS = {
    "rain": ("01", "effect\\efl_SCR\\online\\online_01\\on01_rain", 1, 3, "Rain (Turbulent Jungle)"),
    "rain_heavy": ("03", "effect\\efl_SCR\\area1_rain", 2, 3, "Rain (The Great Outdoors)"),
    "snow": ("15", "effect\\efl_SCR\\aArea_4\\aArea_4_10\\area410_snow", 1, 1, "Snow (Frozen Wasteland)"),
    "ash": ("00", "effect\\efl_SCR\\online\\online_00\\online00_fallout", 2, 1, "Ash (Desecration)"),
}
SHAPE_BOX = 0x10   # 6 f32: one corner, the other (stock: max then min)
VOLUME_PRIORITY = 7


def _arc(game, m):
    return os.path.join(game, "nativePC", "arcXmlTmpPC", f"aArea_ONLINE_{m}.arc")


def resources(game, kind):
    """{arc entry name: (class, bytes)}: the weather's effect list and everything it names, from its stock map."""
    m, top = PRESETS[kind][:2]
    d = open(_arc(game, m), "rb").read()
    entries = {}
    for n, th, cs, ds, fl, o in arcx.entries(d):
        entries.setdefault(n.lower(), []).append((n, TYPES.get(th, f"0x{th:08x}"), d[o:o + cs] if cs == ds else zlib.decompress(d[o:o + cs])))
    out, todo = {}, [top.lower()]
    while todo:
        k = todo.pop()
        for n, cls, b in entries.get(k, []):
            if (n, cls) in out:
                continue
            out[(n, cls)] = b
            for s in re.findall(rb"[A-Za-z0-9_\\\-]{4,}", b):
                s = s.decode("latin-1").lower()
                if "\\" in s and s in entries:
                    todo.append(s)
    if not out:
        raise SystemExit(f"{top} not in {_arc(game, m)}")
    return out


def scrlist(b, kind):
    """b with the weather's type 16 entry in the first unused (type 0) slot."""
    _m, top, slot = PRESETS[kind][:3]
    x = xfsedit.parse(b)
    for e in x["root"]["mpArray"]:
        if e["mType"] == [0] and e["mListName"] in ([""], []):
            e["mType"], e["mListName"], e["mPara1"] = [16], [top], [slot]
            return xfsedit.write(x)
    raise SystemExit("the scenery list has no free entry for the weather")


def zones(b, weather):
    """a SceneBox (after lp2light: bounds set, one zone in every cell) with weather on in every zone and the
    no-weather volumes added as box zones (weather [1, 0, 0], priority 7) in the cells they cover."""
    import lp2scenebox
    sb = lp2scenebox.parse(b)
    kind = weather.get("type")
    on = kind in PRESETS and float(weather.get("amount", 0)) > 0
    w = (1, 100, PRESETS[kind][3]) if on else (0, 0, 0)
    out = bytearray(b[:sb["at_layouts"]])
    tail = None
    for L in sb["layouts"]:
        body = b[L["at"]:L["end"]]
        k = 8 + (0 if L["shape"] == 1 else 4 * sum(lp2scenebox.SHAPE_FLOATS[L["shape"]]))
        out += body[:k] + struct.pack("<3I", *w) + body[k + 12:]
        if tail is None:
            tail = body[k + 12:]   # the rest of a zone: no fields / effects / wind, the map's fog
    vols = weather.get("volumes") or [] if on else []
    first = len(sb["layouts"])
    for v in vols:
        (x, y, z), (sx, sy, sz) = v["pos"], v["size"]
        hi = (x + abs(sx) / 2, y + abs(sy) / 2, z + abs(sz) / 2)
        lo = (x - abs(sx) / 2, y - abs(sy) / 2, z - abs(sz) / 2)
        out += struct.pack("<II6f3I", VOLUME_PRIORITY, SHAPE_BOX, *hi, *lo, 1, 0, 0) + tail
    struct.pack_into("<I", out, 8, first + len(vols))
    # cells: the grid over the header's x / z bounds, cell = zi * 32 + xi; each lists extra zones to test
    mx, mn = sb["max"], sb["min"]
    span_x, span_z = (mx[0] - mn[0]) or 1.0, (mx[2] - mn[2]) or 1.0
    cell = lambda v, a, s: max(0, min(31, int((v - a) / s * 32)))
    full = 0
    for i, v in enumerate(vols):
        (x, _y, z), (sx, _sy, sz) = v["pos"], v["size"]
        for zi in range(cell(z - abs(sz) / 2, mn[2], span_z), cell(z + abs(sz) / 2, mn[2], span_z) + 1):
            for xi in range(cell(x - abs(sx) / 2, mn[0], span_x), cell(x + abs(sx) / 2, mn[0], span_x) + 1):
                at = 0x24 + 64 * (zi * 32 + xi) + 8
                lst = list(struct.unpack_from("<14i", out, at))
                if -1 in lst:
                    lst[lst.index(-1)] = first + i
                    struct.pack_into("<14i", out, at, *lst)
                else:
                    full += 1
    lp2scenebox.parse(bytes(out))   # still a valid file
    return bytes(out), len(vols), full


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["deps"])
    ap.add_argument("--game", required=True)
    ap.add_argument("type", choices=sorted(PRESETS))
    a = ap.parse_args()
    for (n, cls), b in sorted(resources(a.game, a.type).items()):
        print(f"{n}.{cls}  {len(b)} B")


if __name__ == "__main__":
    sys.exit(main())
