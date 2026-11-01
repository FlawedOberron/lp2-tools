#!/usr/bin/env python3
"""Lossless MT Framework XFS v8 (little-endian) read / write, for editing (xfs.py is the readable dump).

  t = xfstree.read(data); ...edit...; data = xfstree.write(t)

Tree: {"head": bytes 4..8, "classes": [{"hash", "fields": [{"name", "type", "attr", "size", "rest" (12 bytes)}]}],
       "names_tail": bytes after the last field name (kept), "root": Obj}
Obj:  {"cls": class index, "id": u16, "tagbit": tag & 1, "values": [[v, ...] per field]}
Values: nested Obj for types 1 / 2; bytes for raw / vec (0x14, 16 bytes); (cls, path) str pair for resource 0x80;
str for strings (0xE); int / float for scalars. Object size (u32 after the id) is recomputed on write.
"""
import struct

SCALAR = {3: "<B", 4: "<B", 5: "<H", 6: "<I", 7: "<Q", 8: "<b", 9: "<h", 10: "<i", 11: "<q", 12: "<f", 13: "<d"}


def read(b):
    assert b[:4] == b"XFS\0"
    ncls, defsize = struct.unpack_from("<II", b, 8)
    base = 0x10
    offs = struct.unpack_from("<%dI" % ncls, b, base)
    classes = []
    name_offs = []
    for o in offs:
        h, n = struct.unpack_from("<II", b, base + o)
        fields = []
        for k in range(n):
            p = base + o + 8 + 24 * k
            no, t, attr, size = struct.unpack_from("<IBBH", b, p)
            name = b[base + no:b.index(b"\0", base + no)].decode("latin-1")
            name_offs.append(no)
            fields.append({"name": name, "type": t, "attr": attr, "size": size, "rest": b[p + 8:p + 24]})
        classes.append({"hash": h, "fields": fields})
    pos = [base + defsize]

    def cstr():
        e = b.index(b"\0", pos[0]); s = b[pos[0]:e].decode("latin-1"); pos[0] = e + 1; return s

    def obj():
        tag, oid, size = struct.unpack_from("<HHI", b, pos[0]); pos[0] += 8
        start = pos[0]
        c = classes[tag >> 1]
        vals = []
        for f in c["fields"]:
            (cnt,) = struct.unpack_from("<I", b, pos[0]); pos[0] += 4
            vs = []
            t = f["type"]
            for _ in range(cnt):
                if t in (1, 2):
                    vs.append(obj())
                elif t == 0x80:
                    pos[0] += 1
                    vs.append((cstr(), cstr()))
                elif t == 0xE:
                    vs.append(cstr())
                elif t in SCALAR:
                    vs.append(struct.unpack_from(SCALAR[t], b, pos[0])[0]); pos[0] += struct.calcsize(SCALAR[t])
                else:
                    n = 16 if t == 0x14 else f["size"]
                    vs.append(b[pos[0]:pos[0] + n]); pos[0] += n
            vals.append(vs)
        return {"cls": tag >> 1, "id": oid, "tagbit": tag & 1, "values": vals, "_size": size, "_len": pos[0] - start}

    root = obj()
    assert pos[0] == len(b), "%d bytes left" % (len(b) - pos[0])
    return {"head": b[4:8], "classes": classes, "defsize": defsize, "names": b[base:base + defsize], "root": root}


def write(t):
    # class definitions: offsets table, then class records, then the name pool (rebuilt)
    classes = t["classes"]
    ncls = len(classes)
    recs_size = sum(8 + 24 * len(c["fields"]) for c in classes)
    pool, where = bytearray(), {}
    head = 4 * ncls + recs_size
    for c in classes:
        for f in c["fields"]:
            if f["name"] not in where:
                where[f["name"]] = head + len(pool)
                pool += f["name"].encode("latin-1") + b"\0"
    defs = bytearray()
    o = 4 * ncls
    for c in classes:
        defs += struct.pack("<I", o)
        o += 8 + 24 * len(c["fields"])
    for c in classes:
        defs += struct.pack("<II", c["hash"], len(c["fields"]))
        for f in c["fields"]:
            defs += struct.pack("<IBBH", where[f["name"]], f["type"], f["attr"], f["size"]) + f["rest"]
    defs += pool
    while len(defs) % 4:
        defs += b"\0"

    def obj(ob):
        body = bytearray()
        for f, vs in zip(classes[ob["cls"]]["fields"], ob["values"]):
            body += struct.pack("<I", len(vs))
            ty = f["type"]
            for v in vs:
                if ty in (1, 2):
                    body += obj(v)
                elif ty == 0x80:
                    body += b"\x02" + v[0].encode("latin-1") + b"\0" + v[1].encode("latin-1") + b"\0"
                elif ty == 0xE:
                    body += v.encode("latin-1") + b"\0"
                elif ty in SCALAR:
                    body += struct.pack(SCALAR[ty], v)
                else:
                    body += v
        return struct.pack("<HHI", ob["cls"] << 1 | ob["tagbit"], ob["id"], len(body) + SIZE_EXTRA) + body

    return b"XFS\0" + t["head"] + struct.pack("<II", ncls, len(defs)) + bytes(defs) + obj(t["root"])


SIZE_EXTRA = 4   # the stored size counts 4 bytes past the body (checked on stock files)
