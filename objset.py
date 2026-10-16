#!/usr/bin/env python3
"""Lost Planet 2 rObjSet ('OSF\\0') -> placement list (weapons, vehicles, posts...).

  objset.py FILE.rObjSet [--json]

Header 0x30 bytes: u16 counts at 0x0A (group 1), 0x0C (group 2), 0x0E (group 3), 0x10 (group 4).
Records follow in group order; group 1 records are 0x140 bytes, the others 0x120.
Record: +0x00 u32 group, +0x04 u32 phase (0 / 10 / 20; unconfirmed: wave or delay),
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
                            kind=kind, item=item,
                            pos=[round(v, 1) for v in struct.unpack_from("<3f", b, off + 0x40)],
                            rot=[round(v, 1) for v in struct.unpack_from("<3f", b, off + 0x50)],
                            scale=[round(v, 3) for v in struct.unpack_from("<3f", b, off + 0x60)]))
            if grp != g:
                raise ValueError(f"record at {off:#x}: group byte {grp} != {g}, layout guess is wrong")
            off += SIZES[g]
    return counts, out, off


if __name__ == "__main__":
    counts, recs, end = parse(open(sys.argv[1], "rb").read())
    if "--json" in sys.argv:
        print(json.dumps(recs, indent=1))
    else:
        print("counts", counts, f"records end at {end:#x}")
        for r in recs:
            print(r)
