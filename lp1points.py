#!/usr/bin/env python3
"""Lost Planet 1 (Colonies, 360) multiplayer layout points -> JSON (spawns, team spawns, VS, weapons, objects).
  lp1points.py MAP.arc OUT.json        e.g. ZZPack2/s850.arc
Source: tool\\missione0\\sNNN-MV (type 0x71d6a0d4, big-endian 'FSO '), one per mode M (first digit) and
layout variant V (second digit). Unused bytes are uninitialised memory: only the fields below mean anything.
  0x08 u16 point count; points from 0x30, 0xA0 each:
    +0x04 u32 kind: 1-16 single (FFA) starts, 20-23 team spawn groups (16 each; 2-team modes have 20/21 only),
          40 (x14/8, unknown), 30/31 (2-team mode only), 50-52, 61-62, 100 (one each, unknown)
    +0x20 f32x3 position (cm, stage space), +0x34 f32 yaw (degrees, about +Y)
  then objects, 0xB0 each, to the end of the file (unused slots are kind 0):
    +0x00 u32 kind (1 VS, 3 object, 4 weapon), +0x04 u32 VS: 0 / 1, splitting a layout's VS into two halves at
          near-identical spots (one of each pair; LP1's VS amount?) -> "lp1_pair", +0x18 u8 1, u8 category (2 vs, 4 wp, 6 om), u16 model id
          (vs/wp: high byte; om: both bytes), +0x20 f32x3 position, +0x34 f32 yaw
Files with identical contents are merged (their mode/variant ids listed together).
"""
import json, re, struct, sys, zlib
import arcx

POINT_KIND = {**{k: "start" for k in range(1, 17)}, 20: "team_a", 21: "team_b", 22: "team_c", 23: "team_d"}
OBJ_KIND = {1: "vs", 3: "object", 4: "weapon"}


def parse(b):
    if b[:4] != b"\0FSO":
        raise ValueError("not an LP1 FSO layout")
    n = struct.unpack_from(">H", b, 8)[0]
    pts = []
    for k in range(n):
        o = 0x30 + k * 0xA0
        kind = struct.unpack_from(">I", b, o + 4)[0]
        pts.append(dict(kind=kind, role=POINT_KIND.get(kind, f"k{kind}"), pos=struct.unpack_from(">3f", b, o + 0x20),
                        yaw=struct.unpack_from(">f", b, o + 0x34)[0]))
    objs, o = [], 0x30 + n * 0xA0
    while o + 0xB0 <= len(b):
        kind = struct.unpack_from(">I", b, o)[0]
        if kind in OBJ_KIND and b[o + 0x18] == 1:
            cat, mid = b[o + 0x19], struct.unpack_from(">H", b, o + 0x1A)[0]
            model = {2: f"vs{mid >> 8:02x}", 4: f"wp{mid >> 8:02x}", 6: f"om{mid:04x}"}.get(cat, f"c{cat}_{mid:04x}")
            q = dict(kind=kind, role=OBJ_KIND[kind], model=model, pos=struct.unpack_from(">3f", b, o + 0x20),
                     yaw=struct.unpack_from(">f", b, o + 0x34)[0])
            pair = struct.unpack_from(">I", b, o + 4)[0]
            if kind == 1 and pair in (0, 1):
                q["lp1_pair"] = pair
            objs.append(q)
        o += 0xB0
    return dict(points=pts, objects=objs)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    d = open(sys.argv[1], "rb").read()
    sets = {}
    for name, th, cs, ds, _fl, off in arcx.entries(d):
        m = re.fullmatch(r"tool\\missione0\\(s\d+)-(\d)(\d)", name, re.I)
        if th != 0x71d6a0d4 or not m:
            continue
        raw = zlib.decompress(d[off:off + cs]) if cs != ds else d[off:off + cs]
        lay = parse(raw)
        key = json.dumps(lay, sort_keys=True)
        sets.setdefault(key, dict(ids=[], **lay))["ids"].append(m.group(2) + m.group(3))
    out = sorted(sets.values(), key=lambda s: min(s["ids"]))
    for s in out:
        s["ids"].sort()
    json.dump(dict(source=sys.argv[1].split("/")[-1], units="cm, LP1 stage space (Y up)", sets=out), open(sys.argv[2], "w"), indent=1)
    print(f"{len(out)} distinct layouts, " + ", ".join(f"{'/'.join(s['ids'])}: {len(s['points'])}p {len(s['objects'])}o" for s in out[:4]) + " ...")


if __name__ == "__main__":
    main()
