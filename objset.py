#!/usr/bin/env python3
"""Lost Planet 2 rObjSet ('OSF\\0') -> placement list (weapons, vehicles, posts...).

  objset.py FILE.rObjSet [--json]

Header 0x30 bytes: u16 counts at 0x0A (group 1), 0x0C (group 2), 0x0E (group 3), 0x10 (group 4).
Records follow in group order; group 1 records are 0x140 bytes, the others 0x120.
Record (cObjSetDataBase from +0x10: the decompile's offsets are these + 0x10): +0x00 u32 group, +0x04 u32
  controlStatus (0 / 10 / 20, VS too; meaning unconfirmed), +0x74 u32 mUserData[16] (copied to the object's
  mUserWork; weapons / VS: [2] +0x7c dig pile model 0 om8100, 1 om8103, 2 om8104, [3] +0x80 digs to uncover
  (0 = not buried), [4] +0x84 sink depth cm, [5] +0x88 pile height),
  +0x18 u8 1, u8 kind (2 vehicle, 4 weapon, 6 post), u16 item id (weapon / VS / post type),
  +0x40 f32 pos[3] (cm), +0x50 f32 rot[3] (deg), +0x60 f32 scale[3].
Group meaning, inferred from contents: 1 = vehicles (VS), 3 = posts and gimmicks, 4 = weapon pickups.
"""
import json, struct, sys

SIZES = {1: 0x140, 2: 0x120, 3: 0x120, 4: 0x120}
NAMES = {1: "vehicle", 2: "group2", 3: "post", 4: "weapon"}


def parse(b):
    assert b[:4] == b"OSF\0", "not an OSF file"
    counts = dict(zip((1, 2, 3, 4), struct.unpack_from("<4H", b, 0x0A)))
    off, out = 0x30, []
    for g in (1, 2, 3, 4):
        for _ in range(counts[g]):
            grp = struct.unpack_from("<I", b, off)[0]
            _, kind, item = struct.unpack_from("<BBH", b, off + 0x18)
            out.append(dict(group=NAMES[g], phase=struct.unpack_from("<I", b, off + 4)[0],
                            dig=struct.unpack_from("<I", b, off + 0x80)[0],
                            kind=kind, item=item,
                            pos=[round(v, 1) for v in struct.unpack_from("<3f", b, off + 0x40)],
                            rot=[round(v, 1) for v in struct.unpack_from("<3f", b, off + 0x50)],
                            scale=[round(v, 3) for v in struct.unpack_from("<3f", b, off + 0x60)]))
            if grp != g:
                raise ValueError(f"record at {off:#x}: group byte {grp} != {g}, layout guess is wrong")
            off += SIZES[g]
    return counts, out, off


def reindex(b):
    """rebuild the trailer from the records, so added / removed records spawn. After the records: u32 x u16 @0x12:
    128 phase starts (index into this same table), then per phase [0, 0, n, n x (group << 16 | index in group)]
    (phase = record +0x04; the spawner FUN_00f742f0 creates only the records listed for a phase), then u16 @0x14
    u32 types {0, item >> 8, item & 0xff, kind} in first-seen order. Group 0 (0x130-byte records, header u16 @0x08)
    is never used by stock files."""
    cnt = struct.unpack_from("<5H", b, 0x08)
    assert cnt[0] == 0, "group 0 records"
    off, phases, types = 0x30, {}, []
    for g in (1, 2, 3, 4):
        for i in range(cnt[g]):
            phases.setdefault(struct.unpack_from("<I", b, off + 4)[0], []).append(g << 16 | i)
            kind, item = struct.unpack_from("<BH", b, off + 0x19)
            t = struct.pack(">xHB", item, kind)
            if t not in types:
                types.append(t)
            off += SIZES[g]
    assert all(p < 128 for p in phases), sorted(phases)
    starts, body = [], []
    for p in range(128):
        starts.append(128 + len(body))
        ids = phases.get(p, [])
        body += [0, 0, len(ids)] + ids
    tab = starts + body
    out = bytearray(b[:off]) + struct.pack(f"<{len(tab)}I", *tab) + b"".join(types)
    struct.pack_into("<2H", out, 0x12, len(tab), len(types))
    return bytes(out)


if __name__ == "__main__":
    counts, recs, end = parse(open(sys.argv[1], "rb").read())
    if "--json" in sys.argv:
        print(json.dumps(recs, indent=1))
    else:
        print("counts", counts, f"records end at {end:#x}")
        for r in recs:
            print(r)
