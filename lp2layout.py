#!/usr/bin/env python3
"""Move a stock LP2 map's spawns (rInitPosSet) and VS / weapon pickups (rObjSet) onto an LP1 layout.

  lp2layout.py [--lp1-vs] POINTS.json IN_DIR OUT_DIR

Authored layouts (Blender lp2_map_markers export, "lp2": true): every marker carries its LP2 item id, tier
(objset +0x04 controlStatus: 0 / 10 / 20; stock values kept unless a marker gives one), "item" on LP1-layout weapons (explicit pickup id, else the stock record's), "tier" on LP1-layout VS / weapons
(the editor's VS tier; else the stock record's), "dig" / "dig_pile" (buried:
digs to uncover, pile model 0-2; see put_dig) and game types ("modes": team, slayer,
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
is needed. A file's variant (-00 .. -03) takes the set of that variant whose "modes" lists the file's game type
(the editor's set game types), else the LP1 layout with id '0<variant>' (mode 0).
rInitPosSet kinds -> LP1 point roles:
  0 FFA starts -> start, 1 / 2 team A / B -> team_a / team_b, 3 (5 in Kojin, 8 in Fox) -> k40,
  6 / 7 (one each, team modes) -> k30 / k31.  Roles run out -> wrap around.
rObjSet: group 1 (VS) -> LP1 'vs' objects, group 4 (weapons) -> LP1 'weapon' objects, then its k40 points
(14, unknown role), then its FFA starts; stock records beyond those are dropped (the group count
shrinks). Group 3 (posts, gimmicks) -> the layout's 'object' markers with an om71xx model (data posts, copies of
a stock post record); the stock map's own posts and gimmicks never stay. The Common file is emptied.
VS / weapons beyond the stock count (LP1's VS with --lp1-vs, "placed": true VS and any 'weapon'
objects from the editor) are copies of the group's first record; a placed VS's type is its model ('vsXX'). Authored layouts: the mode-less -Common file's
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
    """the file's variant's set: the one whose "modes" (the editor's set game types) has the file's game type, else
    the LP1 mode 0 set ('0<variant>')."""
    m = re.search(r"-(\d\d)$", name)
    v = m.group(1)[1] if m else "0"
    mode = file_mode(name)
    mine = [s for s in points["sets"] if any(str(i)[1:2] == v for i in s.get("ids", []))]
    for s in mine:
        if mode and mode in s.get("modes", []):
            return s
    return next((s for s in points["sets"] if "0" + v in s["ids"]), points["sets"][0])


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


def put_dig(rec, q):
    """buried ("dig here" pile): mUserData[2..5] (+0x7c pile model, +0x80 digs to uncover, +0x84 / +0x88 sink depth
    and pile height, 0 = the game's defaults), read by uWeapon / uVitalSuit::vf5 as mUserWork[2..5]. Stock records
    carry their own (Desecration has 50 buried items): a copy must not bury what the layout doesn't."""
    n = int(q.get("dig", 0))
    struct.pack_into("<4I", rec, 0x7C, int(q.get("dig_pile", 0)) if n else 0, n, 0, 0)


def put_tier(rec, q):
    """the lobby's "VS on map" level the record needs (+0x04: 0 / 10 / 20); without one the stock record's stays."""
    if "tier" in q:
        struct.pack_into("<I", rec, 0x04, int(q["tier"]))


def put_object(rec, q, g):
    struct.pack_into("<3f", rec, 0x40, *q["pos"])
    struct.pack_into("<f", rec, 0x54, q["yaw"])
    struct.pack_into("<H", rec, 0x1A, q["item"])
    put_tier(rec, q)
    if g in (1, 4):
        put_dig(rec, q)
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
    # LP1 lists only ~2 weapon pickups per layout: the rest go on its k40 points, then its FFA starts (not in an
    # explicit layout, lp2convert.py: its weapon markers are all the pickups)
    if not lay.get("explicit"):
        src[4] += [p for p in lay["points"] if p["role"] == "k40"] + [p for p in lay["points"] if p["role"] == "start"]
    posts = [o for o in lay["objects"] if o["role"] == "object" and str(o.get("model", "")).startswith("om71")]
    out, off, new_counts = bytearray(b[:0x30]), 0x30, {}
    for g in (1, 2, 3, 4):
        kept = 0
        first = b[off:off + objset.SIZES[g]]
        if g == 3:
            # the stock map's posts and gimmicks -> the layout's posts only (copies of a stock post record)
            recs = [b[off + i * objset.SIZES[3]:off + (i + 1) * objset.SIZES[3]] for i in range(counts[3])]
            off += counts[3] * objset.SIZES[3]
            tpl = next((q for q in recs if is_post(q)), None)
            if posts and tpl is None:
                print(f"  {len(posts)} posts dropped: the stock file has no post record to copy", file=sys.stderr)
            for q in posts if tpl is not None else []:
                rec = bytearray(tpl)
                struct.pack_into("<3f", rec, 0x40, *q["pos"])
                struct.pack_into("<f", rec, 0x54, q["yaw"])
                struct.pack_into("<I", rec, 0x110, kept)
                out += rec
                kept += 1
            new_counts[3] = kept
            continue
        for i in range(counts[g]):
            rec = bytearray(b[off:off + objset.SIZES[g]])
            off += objset.SIZES[g]
            if g in src:
                if i >= len(src[g]):
                    continue
                q = src[g][i]
                struct.pack_into("<3f", rec, 0x40, *q["pos"])
                struct.pack_into("<f", rec, 0x54, q["yaw"])  # rot y
                if g in (1, 4):
                    put_dig(rec, q)
                    put_tier(rec, q)
                if g == 4 and "item" in q:  # explicit pickup (editor): this weapon whatever the loadout / stock record
                    struct.pack_into("<H", rec, 0x1A, int(q["item"]))
                if g == 1 and (lp1_vs or q.get("placed")):
                    struct.pack_into("<H", rec, 0x1A, int(q["model"][2:], 16))  # LP2 VS type = LP1 id / the editor's pick
            out += rec
            kept += 1
        # more VS (LP1's, or placed in the editor) or weapons placed in the editor than the stock layout has:
        # copies of the group's first record
        extra = []
        if g == 1:
            extra = [q for q in src[1][counts[1]:] if lp1_vs or q.get("placed")]
        elif g == 4:
            extra = [q for q in src[4][counts[4]:] if q.get("role") == "weapon"]
        if extra and not counts[g]:
            print(f"  {len(extra)} extra group {g} markers dropped: the stock file has no record to copy", file=sys.stderr)
            extra = []
        for q in extra:
            rec = bytearray(first)
            struct.pack_into("<3f", rec, 0x40, *q["pos"])
            struct.pack_into("<f", rec, 0x54, q["yaw"])
            if g == 1:
                struct.pack_into("<H", rec, 0x1A, int(q["model"][2:], 16))
            elif "item" in q:
                struct.pack_into("<H", rec, 0x1A, int(q["item"]))
            put_dig(rec, q)
            put_tier(rec, q)
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
        elif ext == ".osf" and not mode:
            out, c0, c1 = drop_gimmicks(b)   # the Common file (above)
            note = f" gimmicks {c0[2]}+{c0[3]}->{c1[2]}+{c1[3]}"
        elif ext == ".osf":
            out, c0, c1 = patch_objset(b, lay, lp1_vs)
            note = f" VS {c0[1]}->{c1[1]}, posts+gimmicks {c0[3]}->{c1[3]}, weapons {c0[4]}->{c1[4]}"
        else:
            continue
        open(os.path.join(dst, f), "wb").write(out)
        print(f"{name}: LP1 {'/'.join(lay['ids'])}{note}")


if __name__ == "__main__":
    main()
