#!/usr/bin/env python3
"""Xbox / Xbox 360 disc image (XDVDFS) lister/extractor. Read-only; never runs anything from the image.
  xiso.py list IMAGE.iso [FILTER]          paths containing FILTER (case-insensitive)
  xiso.py x IMAGE.iso OUT_DIR [FILTER]     extract matching files
Volume descriptor: sector 32 of the game partition ('MICROSOFT*XBOX*MEDIA', u32 root sector,
u32 root size). Partition offset: 0 (Xbox), 0xFD90000 (360 XGD2), 0x2080000 (XGD3), 0x18300000 (XGD1).
Directory entry: u16 left, u16 right (in 4-byte units from the table start; 0xFFFF = sector padding),
u32 sector, u32 size, u8 attributes (0x10 = directory), u8 name length, name.
"""
import os, struct, sys

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
OFFSETS = (0, 0xFD90000, 0x2080000, 0x18300000)


def open_image(path):
    f = open(path, "rb")
    for base in OFFSETS:
        f.seek(base + 32 * SECTOR)
        h = f.read(28)
        if h[:20] == MAGIC:
            root, size = struct.unpack_from("<II", h, 20)
            return f, base, root, size
    raise SystemExit("no XDVDFS volume found")


def walk(f, base, sector, size, prefix=""):
    f.seek(base + sector * SECTOR)
    table = f.read(size)
    seen, stack = set(), [0]
    while stack:
        off = stack.pop()
        if off in seen or off + 14 > len(table):
            continue
        seen.add(off)
        left, right, sec, fsize, attr, nlen = struct.unpack_from("<HHIIBB", table, off)
        if left == 0xFFFF:
            continue
        name = table[off + 14:off + 14 + nlen].decode("latin-1")
        if left:
            stack.append(left * 4)
        if right:
            stack.append(right * 4)
        path = prefix + name
        if attr & 0x10:
            if fsize:
                yield from walk(f, base, sec, fsize, path + "/")
        else:
            yield path, sec, fsize


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("list", "x"):
        raise SystemExit(__doc__)
    f, base, root, size = open_image(sys.argv[2])
    out = sys.argv[3] if sys.argv[1] == "x" else None
    filt = (sys.argv[4] if out else (sys.argv[3] if len(sys.argv) > 3 else "")).lower()
    for path, sec, fsize in sorted(walk(f, base, root, size)):
        if filt not in path.lower():
            continue
        if out is None:
            print(f"{fsize:12d}  {path}")
            continue
        dst = os.path.abspath(os.path.join(out, *path.split("/")))
        if os.path.commonpath([dst, os.path.abspath(out)]) != os.path.abspath(out):
            raise SystemExit(f"refusing path outside OUT_DIR: {path}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        f.seek(base + sec * SECTOR)
        with open(dst, "wb") as o:
            left = fsize
            while left:
                chunk = f.read(min(left, 1 << 20))
                o.write(chunk)
                left -= len(chunk)


if __name__ == "__main__":
    main()
