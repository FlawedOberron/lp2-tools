#!/usr/bin/env python3
"""Havok binary packfile (magic 57e0e057 10c0c010) reader: sections, fixups, objects.

  hkpack.py FILE        list the objects (offset in data section, class, size to the next object)

Header (0x40, in the file's byte order: Xbox 360 files are big-endian): magic x2, u32 user tag, u32 file version (2 = Havok 4.x / LP1, 7 = 6.x / LP2),
u8 x4 layout rules (pointer size 4, little endian, reuse padding, empty base class), u32 num sections,
u32 contents section index, u32 contents offset, u32 contents class name section index, u32 offset,
char[16] contents version ("Havok-6.6.0-r1"; v2 files have none), u32 flags, u32 pad.
Section headers (0x30 each): char[19] tag + 0xff, u32 absolute data start,
then offsets relative to the data start: local fixups, global fixups, virtual fixups, exports, imports, end
(v2: absent ones are -1; LP1 files have 5 sections: classnames, classindex, dataindex, data, types).
Local fixups: (u32 src, u32 dst) pairs, same section; global: (src, dst section, dst); virtual: (src, class
name section, class name offset) = one per object. Fixup lists are padded with 0xffffffff.
"""
import struct, sys


def read(b):
    magic = b[:8]
    if magic != bytes.fromhex("57e0e05710c0c010"):
        raise ValueError("not a Havok packfile")
    E = "<" if b[0x11] else ">"  # layout rules: little endian (0 on Xbox 360)
    ver, = struct.unpack_from(E + "I", b, 0x0C)
    nsec, = struct.unpack_from(E + "I", b, 0x14)
    hsize = 0x30
    secs = []
    for i in range(nsec):
        o = 0x40 + i * hsize
        tag = b[o:o + 19].split(b"\0")[0].decode()
        start, lf, gf, vf, ex, im, end = struct.unpack_from(E + "7I", b, o + 20)
        secs.append(dict(tag=tag, start=start, local=lf, glob=gf, virt=vf, exports=ex, imports=im, end=end))
    def pairs(s, a, z, n):
        out = []
        for o in range(s["start"] + a, min(s["start"] + z, len(b) - 4 * n + 1), 4 * n):
            v = struct.unpack_from(f"{E}{n}I", b, o)
            if v[0] != 0xFFFFFFFF:
                out.append(v)
        return out
    for s in secs:
        s["locals"] = pairs(s, s["local"], s["glob"], 2)
        s["globals"] = pairs(s, s["glob"], s["virt"], 3)
        # v2 (Havok 4) marks absent tables with -1: the virtual fixups then run to the next present offset
        vend = next(x for x in (s["exports"], s["imports"], s["end"]) if x != 0xFFFFFFFF)
        s["virtuals"] = pairs(s, s["virt"], vend, 3)
    names = secs[0]
    def cname(sec, off):
        o = secs[sec]["start"] + off
        return b[o:b.index(b"\0", o)].decode()
    data = next(s for s in secs if s["tag"] == "__data__")
    objs = sorted((src, cname(sec, off)) for src, sec, off in data["virtuals"])
    return dict(E=E, version=ver, sections=secs, objects=objs, data=data)


if __name__ == "__main__":
    b = open(sys.argv[1], "rb").read()
    p = read(b)
    d = p["data"]
    print(f"version {p['version']}, sections {[s['tag'] for s in p['sections']]}, data {d['local']:#x} bytes, "
          f"{len(d['locals'])} local / {len(d['globals'])} global fixups")
    objs = p["objects"] + [(d["local"], "<end>")]
    for (o, c), (n, _) in zip(objs, objs[1:]):
        print(f"  {o:#08x} {c:28} {n - o:#x}")
