#!/usr/bin/env python3
"""MT Framework XFS v8 (little-endian) read / write that keeps a file's own class table, for editing lists:
objects are {"_cls": class index, "_id": u16, field name: [values]}; nested objects (types 1 / 2) are dicts,
type 0x0e strings are str (NUL-terminated), type 0x80 resource references (u8 2 + class name + path, both
NUL-terminated) are [class, path] (another first byte: no resource, kept as that byte), scalars are numbers,
everything else stays raw bytes.

  xfsedit.py FILE             dump

Object: u16 (class index << 1 | 1), u16 id, u32 size (4 + its fields' bytes), then per field u32 count + values.
"""
import json, struct, sys

SCALAR = {3: "<B", 4: "<B", 5: "<H", 6: "<I", 7: "<Q", 8: "<b", 9: "<h", 10: "<i", 11: "<q", 12: "<f", 13: "<d"}


def parse(b):
    assert b[:4] == b"XFS\0", "not an XFS v8 file"
    ncls, defsize = struct.unpack_from("<II", b, 0x08)
    base = 0x10
    offs = struct.unpack_from(f"<{ncls}I", b, base)
    classes = []
    for o in offs:
        h, n = struct.unpack_from("<II", b, base + o)
        fields = []
        for k in range(n):
            no, t, attr, size = struct.unpack_from("<IBBH", b, base + o + 8 + 24 * k)
            fields.append((b[base + no:b.index(b"\0", base + no)].decode(), t, size))
        classes.append(fields)
    pos = [base + defsize]

    def u(fmt):
        v = struct.unpack_from(fmt, b, pos[0])
        pos[0] += struct.calcsize(fmt)
        return v

    def obj():
        tag, oid, size = u("<HHI")
        out = {"_cls": tag >> 1, "_id": oid}
        for name, t, fsize in classes[tag >> 1]:
            (cnt,) = u("<I")
            vals = []
            for _ in range(cnt):
                if t in (1, 2):
                    vals.append(obj())
                elif t == 0x0e:
                    end = b.index(b"\0", pos[0])
                    vals.append(b[pos[0]:end].decode("latin-1"))
                    pos[0] = end + 1
                elif t == 0x80:
                    k = b[pos[0]]
                    pos[0] += 1
                    if k == 2:
                        ref = []
                        for _ in range(2):
                            end = b.index(b"\0", pos[0])
                            ref.append(b[pos[0]:end].decode("latin-1"))
                            pos[0] = end + 1
                        vals.append(ref)
                    else:
                        vals.append(k)
                elif t in SCALAR:
                    vals.append(u(SCALAR[t])[0])
                else:
                    vals.append(b[pos[0]:pos[0] + fsize])
                    pos[0] += fsize
            out[name] = vals
        return out

    root = obj()
    if pos[0] != len(b):
        raise ValueError(f"parsed {pos[0]} of {len(b)} bytes")
    return {"head": b[:base + defsize], "classes": classes, "root": root}


def write(x):
    classes = x["classes"]

    def obj(o):
        body = bytearray()
        for name, t, fsize in classes[o["_cls"]]:
            vals = o[name]
            body += struct.pack("<I", len(vals))
            for v in vals:
                if t in (1, 2):
                    body += obj(v)
                elif t == 0x0e:
                    body += v.encode("latin-1") + b"\0"
                elif t == 0x80:
                    body += (b"\2" + "\0".join(v).encode("latin-1") + b"\0") if isinstance(v, list) else bytes([v])
                elif t in SCALAR:
                    body += struct.pack(SCALAR[t], v)
                else:
                    body += v
        return struct.pack("<HHI", o["_cls"] << 1 | 1, o["_id"], 4 + len(body)) + bytes(body)

    return x["head"] + obj(x["root"])


if __name__ == "__main__":
    d = parse(open(sys.argv[1], "rb").read())
    print(json.dumps(d["root"], indent=1, default=lambda v: v.hex()))
