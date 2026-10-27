#!/usr/bin/env python3
"""A custom map takes nothing visible from the stock map it is built on: the base map's own resources
emptied or set to plain defaults (lp2mapc.py calls these on the stock package's files).

  scrlist(b, water)   rScrList (the area's scenery list): the stock map's water scheduler (on00_water: water /
                      z-blur planes, the on00_suimen surface), its falling ash (online00_fallout) and the
                      underwater screen effect (kept when the project has water) -> unused entries (type 0)
  fieldset(b)         rFieldSet (effects placed in the area: online00's fallout_fs1-6) -> no entries
  areahit(b)          rAreaHitLayout (the stock map's trigger zones: radar floor changes and the like, placed
                      for its geometry) -> none
  empty_scheduler(b)  an rScheduler with only its Root (a stock 'Root only' file, given as b)
  blank_texture(b)    an rTexture with all-zero blocks (DXT: transparent black): the radar map images
  neutral_cube(b)     the stage's environment cube (type 6: 27 floats of lighting, 3 channels x 9, then the
                      faces): flat grey faces and a plain grey light (DC_GREY each channel, the rest 0)
The SceneBox's per-zone fog, weather, field effects, wind and environment textures: lp2scenebox.neutral.
Gimmicks and posts in the object sets: lp2layout.py.
"""
import struct
import sys

import xfsedit

DROP = ("effect\\efl_scr\\online\\online_00\\on00_water", "effect\\efl_scr\\online\\online_00\\online00_fallout")
UNDERWATER = "effect\\efl_scr\\area4_underwater0"
DC_GREY = 2.0   # stock online00's is 1.9 / 2.0 / 2.1


def scrlist(b, water=False):
    x = xfsedit.parse(b)
    drop = DROP + (() if water else (UNDERWATER,))
    n = 0
    for e in x["root"]["mpArray"]:
        if e["mListName"] and e["mListName"][0].lower() in drop:
            e["mType"], e["mListName"] = [0], [""]
            for k in range(1, 5):
                e["mPara%d" % k] = [0]
            n += 1
    return xfsedit.write(x), n


def fieldset(b):
    x = xfsedit.parse(b)
    n = 0
    for k in ("mFieldSet", "mE2DSet"):
        for s in x["root"].get(k, []):
            n += len(s["mpArray"])
            s["mpArray"] = []
    return xfsedit.write(x), n


def areahit(b):
    x = xfsedit.parse(b)
    n = len(x["root"]["mpLayoutInfoList"])
    x["root"]["mpLayoutInfoList"] = []
    return xfsedit.write(x), n


def empty_scheduler(root_only):
    if root_only[:4] != b"SDL\0" or struct.unpack_from("<H", root_only, 6)[0] != 1:
        raise ValueError("not a Root-only rScheduler")
    return root_only


def _layout(b):
    d2, d3, fmt = struct.unpack_from("<III", b, 8)
    typ, mips, w, h = d2 & 15, (d2 >> 4) & 31, d2 >> 17, d3 & 0x1FFF
    return typ, mips, w, h, fmt


def blank_texture(b):
    typ, mips, w, h, fmt = _layout(b)
    if typ != 2:
        raise ValueError("not a 2D texture")
    start = 0x14 + 4 * mips
    return b[:start] + bytes(len(b) - start)


def neutral_cube(b):
    typ, mips, w, h, fmt = _layout(b)
    if typ != 6:
        raise ValueError("not a cube texture")
    out = bytearray(b)
    sh = [0.0] * 27
    sh[0] = sh[9] = sh[18] = DC_GREY
    struct.pack_into("<27f", out, 0x14, *sh)
    faces = 6 * mips
    offs = struct.unpack_from(f"<{faces}I", b, 0x14 + 108)
    # 16 B blocks (DXT5 style): alpha 255, colour 565 grey both ends, indices 0; 8 B blocks: the colour half
    grey = struct.pack("<HH", 0x8410, 0x8410) + bytes(4)
    ends = list(offs[1:]) + [len(b)]
    size = (offs[1] - offs[0]) if faces > 1 else len(b) - offs[0]
    level = sum(max(1, (w >> m) // 4) * max(1, (h >> m) // 4) for m in range(mips))
    block = (b"\xff\xff" + bytes(6) + grey) if size >= 16 * level else grey
    for o, e in zip(offs, ends):
        out[o:e] = (block * ((e - o) // len(block) + 1))[:e - o]
    return bytes(out)


if __name__ == "__main__":
    sys.exit(__doc__)
