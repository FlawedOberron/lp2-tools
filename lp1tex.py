#!/usr/bin/env python3
"""Lost Planet 1 rTexture -> DDS. PC (MT 'TEX\\0' v0x70) and Xbox 360 Colonies ('\\0XET' v0x66).
  lp1tex.py IN OUT.dds
PC: 0x04 u16 version (0x70), 0x08 u8 mip count, 0x09 u8 faces (1), 0x0C u16 width, 0x0E u16 height,
  0x14 fourcc (DXT1/DXT5), 0x18 4 floats, 0x28 u32[mips] offsets of each mip (top first).
360: same header, big-endian; 0x14 = GPU texture format (low 6 bits: 0x12 DXT1, 0x14 DXT4/5,
  0x3B DXT5A (= BC4), 0x3C CTX1 (2-channel normal map), 0x06 8:8:8:8 ARGB, tiled per texel). Data is tiled (XGAddress2DTiledOffset over
  4x4 blocks, 32x32-block macro tiles) and 16-bit byte-swapped. Only the top mip is converted.
"""
import struct, sys

FMT360 = {0x12: ("DXT1", 8), 0x14: ("DXT5", 16), 0x3B: ("ATI1", 8), 0x3C: ("CTX1", 8)}


def read_tex(b):
    if b[:4] == b"TEX\0" and struct.unpack_from("<H", b, 4)[0] == 0x70:
        mips = b[8]
        w, h = struct.unpack_from("<HH", b, 0x0C)
        offs = struct.unpack_from(f"<{mips}I", b, 0x28)
        return dict(w=w, h=h, mips=mips, fourcc=b[0x14:0x18], data=b[offs[0]:])
    if b[:4] == b"\0XET" and struct.unpack_from(">H", b, 4)[0] == 0x66:
        mips = b[8]
        w, h = struct.unpack_from(">HH", b, 0x0C)
        fmt = struct.unpack_from(">I", b, 0x14)[0] & 0x3F
        off = struct.unpack_from(">I", b, 0x28)[0]
        if fmt == 0x06:  # 8:8:8:8, one big-endian ARGB u32 per texel, tiled per texel
            px = untile(b[off:], w, h, 4)
            rgba = bytearray(len(px))
            rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = px[1::4], px[2::4], px[3::4], px[0::4]
            return dict(w=w, h=h, mips=1, fourcc=None, rgba=bytes(rgba))
        if fmt not in FMT360:
            raise ValueError(f"360 texture format {fmt:#x} not handled")
        name, bs = FMT360[fmt]
        data = untile(swap16(b[off:]), max(1, w // 4), max(1, h // 4), bs)
        if name == "CTX1":
            return dict(w=w, h=h, mips=1, fourcc=None, rgba=decode_ctx1(data, w, h))
        if name == "ATI1":  # BC4 masks: decoded, since not every DDS reader takes BC4
            return dict(w=w, h=h, mips=1, fourcc=None, rgba=decode_bc4(data, w, h))
        return dict(w=w, h=h, mips=1, fourcc=name.encode(), data=data)
    raise ValueError("not an LP1 TEX (PC v0x70 or 360 v0x66)")


def swap16(d):
    d = bytearray(d[:len(d) & ~1])
    d[0::2], d[1::2] = d[1::2], d[0::2]
    return bytes(d)


def tiled_offset(x, y, width, log_bpp):
    """XGAddress2DTiledOffset, in elements (here: 4x4 blocks of 2**log_bpp bytes)."""
    aligned = (width + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (aligned >> 5)) << (log_bpp + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << log_bpp
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + log_bpp)) + ((y & 1) << 4)
    return (((off & ~511) << 3) + ((off & 448) << 2) + (off & 63) + ((y & 16) << 7)
            + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> log_bpp


def untile(src, bw, bh, bs):
    log_bpp = {4: 2, 8: 3, 16: 4}[bs]
    out = bytearray(bw * bh * bs)
    for y in range(bh):
        for x in range(bw):
            s = tiled_offset(x, y, bw, log_bpp) * bs
            d = (y * bw + x) * bs
            out[d:d + bs] = src[s:s + bs]
    return bytes(out)


def decode_ctx1(data, w, h):
    """CTX1: x0 y0 x1 y1 (u8) + 32 bits of 2-bit indices; z rebuilt. -> RGBA8 rows."""
    out = bytearray(w * h * 4)
    bw = max(1, w // 4)
    for by in range(max(1, h // 4)):
        for bx in range(bw):
            o = (by * bw + bx) * 8
            x0, y0, x1, y1 = data[o:o + 4]
            bits = struct.unpack_from("<I", data, o + 4)[0]
            pal = [(x0, y0), (x1, y1), ((2 * x0 + x1) // 3, (2 * y0 + y1) // 3), ((x0 + 2 * x1) // 3, (y0 + 2 * y1) // 3)]
            for i in range(16):
                px, py = pal[(bits >> (2 * i)) & 3]
                nx, ny = px / 127.5 - 1, py / 127.5 - 1
                nz = max(0.0, 1 - nx * nx - ny * ny) ** 0.5
                X, Y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if X < w and Y < h:
                    d = (Y * w + X) * 4
                    out[d:d + 4] = bytes((px, py, int((nz * 0.5 + 0.5) * 255), 255))
    return bytes(out)


def decode_bc4(data, w, h):
    """BC4 (DXT5A): one channel, DXT5 alpha-block encoding. -> grey RGBA8 rows."""
    out = bytearray(w * h * 4)
    bw = max(1, w // 4)
    for by in range(max(1, h // 4)):
        for bx in range(bw):
            o = (by * bw + bx) * 8
            a0, a1 = data[o], data[o + 1]
            bits = int.from_bytes(data[o + 2:o + 8], "little")
            if a0 > a1:
                pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
            else:
                pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
            for i in range(16):
                g = pal[(bits >> (3 * i)) & 7]
                X, Y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if X < w and Y < h:
                    d = (Y * w + X) * 4
                    out[d:d + 4] = bytes((g, g, g, 255))
    return bytes(out)


def to_dds(t):
    caps = 0x1000 | (0x400000 | 0x8 if t["mips"] > 1 else 0)
    if t.get("rgba") is not None:  # uncompressed RGBA8
        hdr = struct.pack("<4sIIIIIII44x", b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000, t["h"], t["w"], t["w"] * 4, 0, 1)
        hdr += struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0xFF, 0xFF00, 0xFF0000, 0xFF000000)
        return hdr + struct.pack("<IIII4x", 0x1000, 0, 0, 0) + t["rgba"]
    block = 8 if t["fourcc"] in (b"DXT1", b"ATI1") else 16
    linear = max(1, (t["w"] + 3) // 4) * max(1, (t["h"] + 3) // 4) * block
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if t["mips"] > 1 else 0)
    hdr = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, t["h"], t["w"], linear, 0, t["mips"])
    hdr += struct.pack("<II4s20x", 32, 0x4, t["fourcc"])
    hdr += struct.pack("<IIII4x", caps, 0, 0, 0)
    return hdr + t["data"][:linear] if t["mips"] == 1 else hdr + t["data"]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    open(sys.argv[2], "wb").write(to_dds(read_tex(open(sys.argv[1], "rb").read())))
