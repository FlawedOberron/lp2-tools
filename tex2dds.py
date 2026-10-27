#!/usr/bin/env python3
"""Lost Planet 2 rTexture (MT 'TEX\\0' v0x87) -> DDS.

  tex2dds.py IN.rTexture [OUT.dds]      one file
  tex2dds.py -r DIR                     every *.rTexture under DIR, DDS written alongside

Header (all little-endian):
  0x00 'TEX\\0'   0x04 u16 version (0x87)
  0x08 u32: type[0:4] (2 = 2D, 6 = cube), mips[4:9], ?[9:17], width[17:30]
  0x0C u32: height[0:13], depth/count[13:21]
  0x10 u32: format[0:8]
  cube only: 27 floats (probably SH lighting) at 0x14
  then u32 offsets[mips * faces] (face-major), then pixel data.
Format codes were mapped from byte counts and name suffixes, so treat
FORMATS as best-known, not authoritative.
"""
import os, struct, sys

# code -> (FourCC or None, bytes per 4x4 block or per pixel, is_block)
FORMATS = {
    19: (b"DXT1", 8, True),   # base colour / lightmaps / cubes
    25: (b"DXT1", 8, True),   # masks (OM/MM)
    23: (b"DXT5", 16, True),  # colour + alpha
    31: (b"DXT5", 16, True),  # normal maps (likely DXT5nm swizzle)
    32: (b"DXT5", 16, True),  # lightmaps
    42: (b"DXT5", 16, True),  # flash/UI HQ
    39: (None, 4, False),     # 32-bit RGBA, uncompressed
    2: (b"\x71\0\0\0", 8, False),  # D3DFMT_A16B16G16R16F
}


def parse(b):
    if b[:4] != b"TEX\0":
        raise ValueError("not a TEX file")
    d2, d3, d4 = struct.unpack_from("<III", b, 8)
    t = dict(type=d2 & 0xF, mips=(d2 >> 4) & 0x1F, width=(d2 >> 17) & 0x1FFF,
             height=d3 & 0x1FFF, fmt=d4 & 0xFF)
    t["faces"] = 6 if t["type"] == 6 else 1
    tbl = 0x14 + (108 if t["type"] == 6 else 0)
    n = t["mips"] * t["faces"]
    offs = struct.unpack_from(f"<{n}I", b, tbl)
    if offs[0] != tbl + 4 * n:
        raise ValueError(f"offset table mismatch ({offs[0]:#x} != {tbl + 4 * n:#x})")
    t["data"] = b[offs[0]:]
    return t


def dds_header(t):
    fourcc, unit, block = FORMATS[t["fmt"]]
    w, h, mips = t["width"], t["height"], t["mips"]
    top = ((w + 3) // 4) * ((h + 3) // 4) * unit if block else w * h * unit
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | (0x80000 if block else 0x8)
    pitch = top if block else w * unit
    if fourcc:
        pf = struct.pack("<II4sIIIII", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    else:  # A8R8G8B8 layout; swap channels later if colours look wrong
        pf = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    caps = 0x1000 | (0x400008 if mips > 1 else 0) | (0x8 if t["faces"] == 6 else 0)
    caps2 = 0xFE00 if t["faces"] == 6 else 0
    return (b"DDS " + struct.pack("<7I", 124, flags, h, w, pitch, 0, mips) + b"\0" * 44
            + pf + struct.pack("<5I", caps, caps2, 0, 0, 0))


def convert(src, dst):
    t = parse(open(src, "rb").read())
    if t["fmt"] not in FORMATS:
        raise ValueError(f"unknown format {t['fmt']}")
    with open(dst, "wb") as f:
        f.write(dds_header(t) + t["data"])
    return t


def dds_png(path, max_size):
    """a DDS (or any image Pillow reads) -> PNG bytes, the first surface, fitted in max_size; None if unreadable."""
    import io
    from PIL import Image
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        return None
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    im.thumbnail((max_size, max_size))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "-r":
        ok = bad = 0
        for d, _, fs in os.walk(a[1]):
            for fn in fs:
                if fn.endswith(".rTexture"):
                    p = os.path.join(d, fn)
                    try:
                        convert(p, p[: -len(".rTexture")] + ".dds"); ok += 1
                    except Exception as e:
                        bad += 1; print(f"{p}: {e}", file=sys.stderr)
        print(f"converted {ok}, failed {bad}")
    else:
        t = convert(a[0], a[1] if len(a) > 1 else os.path.splitext(a[0])[0] + ".dds")
        print({k: v for k, v in t.items() if k != "data"})


if __name__ == "__main__":
    main()
