#!/usr/bin/env python3
"""Move a stock LP2 map's spawns (rInitPosSet) and VS / weapon pickups (rObjSet) onto an LP1 layout.

  lp2layout.py [--lp1-vs] POINTS.json IN_DIR OUT_DIR

Authored layouts (Blender lp2_map_markers export, "lp2": true): every marker carries its LP2 item id, tier
(objset +0x04: 0 / 10 / 20, the match's VS / weapon amount setting) and game types ("modes": team, slayer,
fox, datapost, counter, egg, vs; from the file name: TeamBattle/Team, KojinBattle/Slayer, FoxBattle/Fox,
...); a file gets only its mode's markers. VS, weapon and post groups are then exactly the markers
(records cloned from stock ones, any count), VS weapon mounts included. Spawn counts stay the stock ones
(rInitPosSet has no writer yet): markers fill them by role, wrapping.
--lp1-vs: VS records take LP1's VS type and count (LP2 keeps LP1's VS under the same ids, uVsXX.arc:
  vs50/51/55/56/66/80/81/82/84/e0 with their own models, 53 -> vs03, 54 -> vs04; see notes/vs-ids.md);
  without it the stock LP2 types stay and only move.

POINTS.json: lp1points.py output. IN_DIR: the stock files as NAME.xfs (rInitPosSet) / NAME.osf (rObjSet),
named as their arc entries (aArea_Online_00-TeamBattle-01, ...). Files are patched in place: the stock
point and object counts, kinds and LP2 item ids stay, only positions and directions change, so no writer
is needed. A file's variant (-00 .. -03) takes the LP1 layout with id '0<variant>' (mode 0).
rInitPosSet kinds -> LP1 point roles:
  0 FFA starts -> start, 1 / 2 team A / B -> team_a / team_b, 3 (5 in Kojin, 8 in Fox) -> k40,
  6 / 7 (one each, team modes) -> k30 / k31.  Roles run out -> wrap around.
rObjSet: group 1 (VS) -> LP1 'vs' objects, group 4 (weapons) -> LP1 'weapon' objects, then its k40 points
(14, unknown role), then its FFA starts; stock records beyond those are dropped (the group count
shrinks). Groups 2 / 3 (posts, gimmicks) are left alone. Authored layouts: the mode-less -Common file's
gimmicks (the stock map's, every mode) are dropped.
Every record has its index within its group at +0x110 (u32, 0..n-1; an index
duplicated is the suspected cause of pickups moving at match start), rewritten for cloned records.
"""
import json, os, re, struct, sys
import objset, xfs

KIND_ROLE = {0: "start", 1: "team_a", 2: "team_b", 3: "k40", 6: "k30", 7: "k31"}
# game type of a file, from its name (rInitPosSet and rObjSet name some modes differently)
MODES = {"teambattle": "team", "team": "team", "kojinbattle": "slayer", "slayer": "slayer", "foxbattle": "fox",
         "fox": "fox", "datapost": "datapost", "counter": "counter", "egg": "egg", "vs": "vs"}


def file_mode(name):
    m = re.search(r"-([a-z]+)-\d\d$", name.lower())
    return MODES.get(m.group(1)) if m else None


def for_mode(lay, mode):
    """a layout set with only the markers of this game type (markers without "modes" are in every one)."""
    keep = lambda r: mode is None or "modes" not in r or mode in r["modes"]
    return dict(lay, points=[p for p in lay["points"] if keep(p)], objects=[o for o in lay["objects"] if keep(o)])


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
        src = by_role.get(KIND_ROLE.get(p["Kind"], "start")) or by_role.get("start")
        if not src:
            raise ValueError("layout has no FFA starts to fall back on")
        k = used.get(id(src), 0)
        used[id(src)] = k + 1
        q = src[k % len(src)]
        struct.pack_into("<3f", b, off, *q["pos"])
        # Dir: u32 count 1, u16 degrees, right after the 16-byte Pos value
        if struct.unpack_from("<I", b, off + 16)[0] != 1:
            raise ValueError("Dir is not where expected")
        struct.pack_into("<H", b, off + 20, int(round(q["yaw"])) % 360)
    return bytes(b)


def is_post(rec):
    return rec[0x19] == 6 and rec[0x1A] == 0x71  # om71xx data posts


def put_object(rec, q, g):
    struct.pack_into("<3f", rec, 0x40, *q["pos"])
    struct.pack_into("<f", rec, 0x54, q["yaw"])
    struct.pack_into("<H", rec, 0x1A, q["item"])
    if "tier" in q:
        struct.pack_into("<I", rec, 0x04, q["tier"])
    if g == 1 and "weapons" in q:  # 4 mounts x 5 B at 0x120: u8 on, u8 4 (weapon), u16 id, u8 0
        for i, (on, wid) in enumerate(q["weapons"][:4]):
            struct.pack_into("<BBHB", rec, 0x120 + 5 * i, on, 4, wid, 0)


def patch_objset_lp2(b, lay, templates):
    """an authored layout (Blender export, "lp2": true): VS, weapons and posts are exactly its markers,
    records cloned from this file's own (or, when it has none, any stock file's) records of the group;
    stock gimmicks in group 3 that are not posts are dropped with the stock posts."""
    counts, _, end = objset.parse(b)
    stock, off = {}, 0x30
    for g in (1, 2, 3, 4):
        stock[g] = []
        for _ in range(counts[g]):
            stock[g].append(bytes(b[off:off + objset.SIZES[g]]))
            off += objset.SIZES[g]
    want = {1: "vs", 3: "post", 4: "weapon"}
    out, new_counts = bytearray(b[:0x30]), {}
    for g in (1, 2, 3, 4):
        if g not in want:
            recs = stock[g]
        else:
            tpl = [r for r in stock[g] if g != 3 or is_post(r)] or templates.get(g, [])
            src = [o for o in lay["objects"] if o["role"] == want[g]]
            if src and not tpl:
                raise ValueError(f"no stock {want[g]} record to copy")
            recs = []
            for i, q in enumerate(src):
                rec = bytearray(tpl[i] if i < len(tpl) else tpl[0])
                put_object(rec, q, g)
                struct.pack_into("<I", rec, 0x110, i)
                recs.append(bytes(rec))
        out += b"".join(recs)
        new_counts[g] = len(recs)
    struct.pack_into("<4H", out, 0x0A, *(new_counts[g] for g in (1, 2, 3, 4)))
    return bytes(out + b[end:]), counts, new_counts


def drop_gimmicks(b):
    """remove groups 2 and 3 (gimmicks, posts) from a file, keeping VS and weapons."""
    counts, _, end = objset.parse(b)
    off, keep = 0x30, {}
    for g in (1, 2, 3, 4):
        keep[g] = b[off:off + counts[g] * objset.SIZES[g]] if g in (1, 4) else b""
        off += counts[g] * objset.SIZES[g]
    out = bytearray(b[:0x30]) + b"".join(keep[g] for g in (1, 2, 3, 4))
    new = {g: len(keep[g]) // objset.SIZES[g] for g in (1, 2, 3, 4)}
    struct.pack_into("<4H", out, 0x0A, *(new[g] for g in (1, 2, 3, 4)))
    return bytes(out + b[end:]), counts, new


def patch_objset(b, lay, lp1_vs=False):
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
                if g == 1 and lp1_vs:
                    struct.pack_into("<H", rec, 0x1A, int(q["model"][2:], 16))  # LP2 VS type = LP1 id
            out += rec
            kept += 1
        # LP1 has more VS than the stock layout: copies of its first VS record
        if g == 1 and lp1_vs and counts[1]:
            first = b[0x30:0x30 + objset.SIZES[1]]
            for q in src[1][counts[1]:]:
                rec = bytearray(first)
                struct.pack_into("<3f", rec, 0x40, *q["pos"])
                struct.pack_into("<f", rec, 0x54, q["yaw"])
                struct.pack_into("<H", rec, 0x1A, int(q["model"][2:], 16))
                struct.pack_into("<I", rec, 0x110, kept)
                out += rec
                kept += 1
        new_counts[g] = kept
    struct.pack_into("<4H", out, 0x0A, *(new_counts[g] for g in (1, 2, 3, 4)))
    return bytes(out + b[end:]), counts, new_counts


def main():
    args = [a for a in sys.argv[1:] if a != "--lp1-vs"]
    if len(args) != 3:
        raise SystemExit(__doc__)
    lp1_vs = "--lp1-vs" in sys.argv
    points = json.load(open(args[0]))
    src, dst = args[1], args[2]
    os.makedirs(dst, exist_ok=True)
    authored = points.get("lp2", False)
    templates = {}  # group -> stock records, for files that have none of a group
    for f in sorted(os.listdir(src)):
        if f.endswith(".osf"):
            b = open(os.path.join(src, f), "rb").read()
            c, _, _ = objset.parse(b)
            off = 0x30
            for g in (1, 2, 3, 4):
                for _ in range(c[g]):
                    rec = b[off:off + objset.SIZES[g]]
                    off += objset.SIZES[g]
                    if g != 3 or is_post(rec):
                        templates.setdefault(g, []).append(rec)
    for f in sorted(os.listdir(src)):
        name, ext = os.path.splitext(f)
        b = open(os.path.join(src, f), "rb").read()
        mode = file_mode(name)
        lay = for_mode(layout_for(points, name), mode)
        if ext == ".xfs":
            out = patch_initpos(b, lay)
            note = ""
        elif ext == ".osf" and authored and mode:
            out, c0, c1 = patch_objset_lp2(b, lay, templates)
            note = f" VS {c0[1]}->{c1[1]}, posts+gimmicks {c0[3]}->{c1[3]}, weapons {c0[4]}->{c1[4]}"
        elif ext == ".osf" and authored:
            # the mode-less Common file: the stock map's gimmicks for every mode (online00: om8322 x11 and
            # the om835a windmill), placed for its own geometry -> dropped; posts stay per mode
            out, c0, c1 = drop_gimmicks(b)
            note = f" gimmicks {c0[2]}+{c0[3]}->{c1[2]}+{c1[3]}"
        elif ext == ".osf":
            out, c0, c1 = patch_objset(b, lay, lp1_vs)
            note = f" VS {c0[1]}->{c1[1]}, weapons {c0[4]}->{c1[4]}"
        else:
            continue
        open(os.path.join(dst, f), "wb").write(out)
        print(f"{name}: LP1 {'/'.join(lay['ids'])}{note}")


if __name__ == "__main__":
    main()
