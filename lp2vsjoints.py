#!/usr/bin/env python3
"""Renumber / add joints in a VS model so an LP1 VS that LP2 ships with another VS's code, motions and effects
(uVs66 runs vs06's, uVs82 vs32's) has its joints where that code looks for them.

  lp2vsjoints.py IN.rModel OUT.rModel [OLD=NEW ...] [+NEW@PARENT ...]

OLD=NEW   joint id OLD becomes NEW (all renames apply at once, so 100=151 37=100 swaps cleanly)
+NEW@P    a new joint NEW on joint P (after the renames), sitting exactly on it: identity local matrix, P's
          inverse bind (stock LP2 models add 200 this way: vs06 on j15, vs32 on j11)
Presets (the ids LP2's own vs06 / vs32 models use for the same spots):
  --preset vs66   31=100 100=150 +200@15      (j31 = vs06's weapon mount j100, j100 = its front tip j150)
  --preset vs82   37=100 38=101 100=151 101=150 +200@11   (shoulder mounts = vs32's 100 / 101)

LP2 rModel ('MOD\\0' v0xC5): u16 bone count at 6, bone block at the offset in 0x24 = n x 24 B records
(u8 joint id, u8 parent bone index, ...), n x 64 B local matrices, n x 64 B inverse binds, then a 256 B
joint id -> bone index table (255 = none). Everything after the block moves by 152 B per added bone; the
section offsets 0x28..0x3C follow it. Vertices index bones directly, so new bones go at the end.
"""
import struct, sys

PRESETS = {
    "vs66": ["31=100", "100=150", "+200@15"],
    "vs82": ["37=100", "38=101", "100=151", "101=150", "+200@11"],
}
IDENTITY = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def fix(b, ops):
    if b[:4] != b"MOD\0":
        raise SystemExit("not an LP2 rModel")
    n = struct.unpack_from("<H", b, 6)[0]
    off = struct.unpack_from("<I", b, 0x24)[0]
    recs = [bytearray(b[off + i * 24:off + i * 24 + 24]) for i in range(n)]
    local = [b[off + n * 24 + i * 64:off + n * 24 + i * 64 + 64] for i in range(n)]
    inv = [b[off + n * 88 + i * 64:off + n * 88 + i * 64 + 64] for i in range(n)]
    end = off + n * 152 + 256
    renames = dict(tuple(map(int, o.split("="))) for o in ops if "=" in o)
    for r in recs:
        if r[0] in renames:
            r[0] = renames[r[0]]
    ids = [r[0] for r in recs]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"duplicate joint ids after renaming: {sorted(ids)}")
    for o in ops:
        if not o.startswith("+"):
            continue
        new, parent = map(int, o[1:].split("@"))
        if new in ids:
            raise SystemExit(f"joint {new} already exists")
        p = ids.index(parent)
        rec = bytearray(recs[p])
        rec[0], rec[1] = new, p
        recs.append(rec)
        local.append(IDENTITY)
        inv.append(inv[p])
        ids.append(new)
    remap = bytearray([255] * 256)
    for i, j in enumerate(ids):
        remap[j] = i
    block = b"".join(recs) + b"".join(local) + b"".join(inv) + bytes(remap)
    grow = len(block) - (end - off)
    out = bytearray(b[:off]) + block + b[end:]
    struct.pack_into("<H", out, 6, len(recs))
    for at in range(0x28, 0x40, 4):  # the sections after the bone block
        v = struct.unpack_from("<I", out, at)[0]
        if v >= end:
            struct.pack_into("<I", out, at, v + grow)
    return bytes(out)


def main():
    a = sys.argv[1:]
    ops = []
    if len(a) >= 2 and a[0] == "--preset":
        ops, a = list(PRESETS[a[1]]), a[2:]
    ops += a[2:]
    if len(a) < 2:
        raise SystemExit(__doc__)
    open(a[1], "wb").write(fix(open(a[0], "rb").read(), ops))
    print(f"{a[1]}: {' '.join(ops)}")


if __name__ == "__main__":
    main()
