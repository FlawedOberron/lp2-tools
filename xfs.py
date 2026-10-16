#!/usr/bin/env python3
"""MT Framework XFS v8 (self-describing serialised objects) -> JSON-ish dump.

  xfs.py FILE [--json]

Layout: 'XFS\\0' u16 ver(8) u16 1 u32 classCount u32 defSize
  u32 classOff[classCount] (relative to 0x10)
  class: u32 hash, u32 nfields, fields[24]: u32 nameOff(rel 0x10) u8 type u8 attr u16 size +12
  data @0x10+defSize: object = u16 (classIdx<<1|1) u16 id u32 size, then per field:
  u32 count, count * value.  type 1/2 = nested object, 0x14 = vec3 (16 bytes).
"""
import json, struct, sys

SCALAR = {3: "<B", 4: "<B", 5: "<H", 6: "<I", 7: "<Q", 8: "<b", 9: "<h", 10: "<i", 11: "<q", 12: "<f", 13: "<d"}


def parse(b, vec_offsets=None):
    """vec_offsets, when a list, collects (field name, byte offset) of every vec3 value."""
    assert b[:4] == b"XFS\0", "not XFS"
    ncls, defsize = struct.unpack_from("<II", b, 0x08)
    base = 0x10
    offs = struct.unpack_from(f"<{ncls}I", b, base)
    def cstr(o):
        return b[o:b.index(b"\0", o)].decode()
    classes = []
    for o in offs:
        h, n = struct.unpack_from("<II", b, base + o)
        fields = []
        for k in range(n):
            no, t, attr, size = struct.unpack_from("<IBBH", b, base + o + 8 + 24 * k)
            fields.append((cstr(base + no), t, size))
        classes.append((h, fields))
    pos = [base + defsize]

    def u(fmt):
        v = struct.unpack_from(fmt, b, pos[0]); pos[0] += struct.calcsize(fmt); return v

    def obj():
        tag, oid, size = u("<HHI")
        ci = tag >> 1
        h, fields = classes[ci]
        out = {"_class": f"{h:08x}"}
        for name, t, size in fields:
            (cnt,) = u("<I")
            vals = []
            for _ in range(cnt):
                if t in (1, 2):
                    vals.append(obj())
                elif t == 0x14:
                    if vec_offsets is not None:
                        vec_offsets.append((name, pos[0]))
                    vals.append([round(x, 2) for x in u("<4f")[:3]])
                elif t in SCALAR:
                    vals.append(u(SCALAR[t])[0])
                else:
                    vals.append(b[pos[0]:pos[0] + size].hex()); pos[0] += size
            out[name] = vals[0] if cnt == 1 and t not in (2,) else vals
        return out

    return obj()


if __name__ == "__main__":
    d = parse(open(sys.argv[1], "rb").read())
    print(json.dumps(d, indent=1))
