#!/usr/bin/env python3
"""Lost Planet 2 (MT Framework, ARC v8) archive lister/extractor.

  arcx.py list  FILE.arc
  arcx.py x     FILE.arc OUTDIR      also writes OUTDIR/.arcorder (entry order + classes)
  arcx.py pack  DIR OUT.arc          repack; uses DIR/.arcorder when present, otherwise every
                                     file whose suffix is a known class (sorted)

Entry: name[64] typehash u32, csize u32, dsize|flags u32, offset u32.
typehash = jamcrc(class name) & 0x7fffffff; class names come from rclasses.txt
(strings 'r*' pulled from LP2DX9.exe). Extracted files get the class as suffix.

Layout written by Capcom (and by pack): header + entry table, padded with zeros to the next
0x8000 boundary, then the zlib streams (default level, '78 9c') back to back, flags always 2.
"""
import os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))


def load_types():
    tab = {}
    p = os.path.join(HERE, "rclasses.txt")
    if os.path.exists(p):
        for c in open(p):
            c = c.strip()
            tab[(zlib.crc32(c.encode()) ^ 0xFFFFFFFF) & 0x7FFFFFFF] = c
    return tab


def entries(data):
    magic, ver, n = struct.unpack_from("<4sHH", data)
    if magic != b"ARC\0":
        raise SystemExit("not an ARC file")
    if ver != 8:
        print(f"warning: ARC version {ver}, expected 8", file=sys.stderr)
    for i in range(n):
        name, th, cs, ds, off = struct.unpack_from("<64sIIII", data, 8 + i * 80)
        yield name.split(b"\0")[0].decode("latin-1"), th, cs, ds & 0x1FFFFFFF, ds >> 29, off


def class_hash(cls):
    if cls.startswith("0x"):
        return int(cls, 16)
    return (zlib.crc32(cls.encode()) ^ 0xFFFFFFFF) & 0x7FFFFFFF


def pack(src, out):
    order = os.path.join(src, ".arcorder")
    if os.path.exists(order):
        items = [ln.rstrip("\n").split("\t") for ln in open(order, encoding="latin-1") if ln.strip()]
    else:
        known = set(load_types().values())
        items = []
        for d, _, fs in os.walk(src):
            for fn in fs:
                base, _, cls = fn.rpartition(".")
                if cls in known:
                    rel = os.path.relpath(os.path.join(d, base), src)
                    items.append((rel.replace(os.sep, "\\"), cls))
        items.sort()
    table, blobs = b"", []
    for name, cls in items:
        raw = open(os.path.join(src, *name.split("\\")) + "." + cls, "rb").read()
        enc = name.encode("latin-1")
        if len(enc) > 63:
            raise SystemExit(f"name too long for the 64-byte field: {name}")
        if len(raw) >= 1 << 29:
            raise SystemExit(f"{name}: too large")
        blobs.append((enc, class_hash(cls), raw, zlib.compress(raw, 6)))
    head = 8 + 80 * len(blobs)
    off = (head + 0x7FFF) // 0x8000 * 0x8000 if blobs else head
    for enc, th, raw, z in blobs:
        table += struct.pack("<64sIIII", enc, th, len(z), len(raw) | 2 << 29, off)
        off += len(z)
    data = struct.pack("<4sHH", b"ARC\0", 8, len(blobs)) + table
    data += b"\0" * ((head + 0x7FFF) // 0x8000 * 0x8000 - head if blobs else 0)
    with open(out, "wb") as f:
        f.write(data + b"".join(z for *_, z in blobs))
    return len(blobs)


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "pack":
        print(f"packed {pack(sys.argv[2], sys.argv[3])} entries into {sys.argv[3]}")
        return
    if len(sys.argv) < 3 or sys.argv[1] not in ("list", "x"):
        raise SystemExit(__doc__)
    types = load_types()
    data = open(sys.argv[2], "rb").read()
    order = []
    for name, th, cs, ds, flags, off in entries(data):
        cls = types.get(th, f"0x{th:08x}")
        if sys.argv[1] == "list":
            print(f"{cls:28} {ds:10} {name}")
            continue
        raw = data[off:off + cs]
        body = zlib.decompress(raw) if cs != ds or raw[:1] == b"\x78" else raw
        out = os.path.join(sys.argv[3], *name.split("\\")) + "." + cls
        # guard against path escape from crafted names
        if os.path.commonpath([os.path.abspath(out), os.path.abspath(sys.argv[3])]) != os.path.abspath(sys.argv[3]):
            raise SystemExit(f"refusing path {name!r}")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(body)
        order.append(f"{name}\t{cls}\n")
    if sys.argv[1] == "x":
        os.makedirs(sys.argv[3], exist_ok=True)
        with open(os.path.join(sys.argv[3], ".arcorder"), "w", encoding="latin-1") as f:
            f.writelines(order)


if __name__ == "__main__":
    main()
