#!/usr/bin/env python3
"""Move a stock LP2 map's spawns (rInitPosSet) and VS / weapon pickups (rObjSet) onto an LP1 layout.

  lp2layout.py POINTS.json IN_DIR OUT_DIR

POINTS.json: lp1points.py output. IN_DIR: the stock files as NAME.xfs (rInitPosSet) / NAME.osf (rObjSet),
named as their arc entries (aArea_Online_00-TeamBattle-01, ...). Files are patched in place: the stock
point and object counts, kinds and LP2 item ids stay, only positions and directions change, so no writer
is needed. A file's variant (-00 .. -03) takes the LP1 layout with id '0<variant>' (mode 0).
rInitPosSet kinds -> LP1 point roles:
  0 FFA starts -> start, 1 / 2 team A / B -> team_a / team_b, 3 (5 in Kojin, 8 in Fox) -> k40,
  6 / 7 (one each, team modes) -> k30 / k31.  Roles run out -> wrap around.
rObjSet: group 1 (VS) -> LP1 'vs' objects, group 4 (weapons) -> LP1 'weapon' objects, then its k40 points
(14, unknown role), then its FFA starts; stock records beyond those are dropped (the group count
shrinks). Groups 2 / 3 (posts, gimmicks) are left alone.
"""
import json, os, re, struct, sys
import objset, xfs

KIND_ROLE = {0: "start", 1: "team_a", 2: "team_b", 3: "k40", 6: "k30", 7: "k31"}


def layout_for(points, name):
    m = re.search(r"-(\d\d)$", name)
    want = "0" + (m.group(1)[1] if m else "0")
    return next((s for s in points["sets"] if want in s["ids"]), points["sets"][0])


def patch_initpos(b, lay):
    b = bytearray(b)
    vecs = []
    root = xfs.parse(bytes(b), vecs)
    pts = root["mInitPosSet"]["mpArray"]
    if len(vecs) != len(pts):
        raise ValueError("Pos offsets do not match the points")
    by_role, used = {}, {}
    for p in lay["points"]:
        by_role.setdefault(p["role"], []).append(p)
    for p, (_, off) in zip(pts, vecs):
        src = by_role.get(KIND_ROLE.get(p["Kind"], "start")) or by_role["start"]
        k = used.get(id(src), 0)
        used[id(src)] = k + 1
        q = src[k % len(src)]
        struct.pack_into("<3f", b, off, *q["pos"])
        # Dir: u32 count 1, u16 degrees, right after the 16-byte Pos value
        if struct.unpack_from("<I", b, off + 16)[0] != 1:
            raise ValueError("Dir is not where expected")
        struct.pack_into("<H", b, off + 20, int(round(q["yaw"])) % 360)
    return bytes(b)


def patch_objset(b, lay):
    counts, recs, end = objset.parse(b)
    src = {1: [o for o in lay["objects"] if o["role"] == "vs"], 4: [o for o in lay["objects"] if o["role"] == "weapon"]}
    # LP1 lists only ~2 weapon pickups per layout: the rest go on its k40 points, then its FFA starts
    src[4] += [p for p in lay["points"] if p["role"] == "k40"] + [p for p in lay["points"] if p["role"] == "start"]
    out, off, new_counts = bytearray(b[:0x30]), 0x30, {}
    for g in (1, 2, 3, 4):
        kept = 0
        for i in range(counts[g]):
            rec = bytearray(b[off:off + objset.SIZES[g]])
            off += objset.SIZES[g]
            if g in src:
                if i >= len(src[g]):
                    continue
                q = src[g][i]
                struct.pack_into("<3f", rec, 0x40, *q["pos"])
                struct.pack_into("<f", rec, 0x54, q["yaw"])  # rot y
            out += rec
            kept += 1
        new_counts[g] = kept
    struct.pack_into("<4H", out, 0x0A, *(new_counts[g] for g in (1, 2, 3, 4)))
    return bytes(out + b[end:]), counts, new_counts


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    points = json.load(open(sys.argv[1]))
    src, dst = sys.argv[2], sys.argv[3]
    os.makedirs(dst, exist_ok=True)
    for f in sorted(os.listdir(src)):
        name, ext = os.path.splitext(f)
        b = open(os.path.join(src, f), "rb").read()
        lay = layout_for(points, name)
        if ext == ".xfs":
            out = patch_initpos(b, lay)
            note = ""
        elif ext == ".osf":
            out, c0, c1 = patch_objset(b, lay)
            note = f" VS {c0[1]}->{c1[1]}, weapons {c0[4]}->{c1[4]}"
        else:
            continue
        open(os.path.join(dst, f), "wb").write(out)
        print(f"{name}: LP1 {'/'.join(lay['ids'])}{note}")


if __name__ == "__main__":
    main()
