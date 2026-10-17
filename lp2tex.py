#!/usr/bin/env python3
"""Lost Planet 2 rTexture writer: image -> 'TEX\\0' v0x87 (DXT1 / DXT5, with mips).

  lp2tex.py IN.png OUT.rTexture --kind bm|nm|mm [--mips N]

  bm  colour map   DXT1 (format 19); an alpha channel with any transparency -> DXT5 (format 23)
  nm  normal map   DXT5nm (format 31): X in alpha, Y in green, red and blue 255 (the game's layout;
                   give a normal tangent-space map, OpenGL / Blender style Y up)
  mm  mask map     DXT1 (format 25)

Width and height must be powers of two (the game's own are 512 x 512 for parts). Mips: the full
chain down to 4 x 4 unless --mips (stock parts: 5). Pure numpy, so it runs inside Blender too:
  import lp2tex; data = lp2tex.encode(rgba_uint8_array, "nm")
Header layout from tex2dds.py (stock files: d2 = type 2 | mips << 4 | 1 << 9 | width << 17,
d3 = height | 1 << 13, d4 = format).
"""
import struct
import sys

import numpy as np

KINDS = {"bm": 19, "bma": 23, "nm": 31, "mm": 25}


def _565(c):
    """float RGB (..., 3) 0-255 -> u16 565"""
    r = np.clip(np.round(c[..., 0] * 31 / 255), 0, 31).astype(np.uint16)
    g = np.clip(np.round(c[..., 1] * 63 / 255), 0, 63).astype(np.uint16)
    b = np.clip(np.round(c[..., 2] * 31 / 255), 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def _unpack565(v):
    r = ((v >> 11) & 31).astype(np.float32) * 255 / 31
    g = ((v >> 5) & 63).astype(np.float32) * 255 / 63
    b = (v & 31).astype(np.float32) * 255 / 31
    return np.stack([r, g, b], -1)


def _blocks(img):
    """(H, W, C) -> (H/4 * W/4, 16, C) in row-major block order"""
    h, w, c = img.shape
    return img.reshape(h // 4, 4, w // 4, 4, c).transpose(0, 2, 1, 3, 4).reshape(-1, 16, c)


def _colour_blocks(rgb, four_colour=True):
    """DXT colour blocks (N, 16, 3) float -> (N, 8) bytes. Endpoints from the block's colour range
    along its main axis (cheap principal axis: the channel-range box diagonal, signed by the
    covariance), indices by nearest palette entry."""
    n = rgb.shape[0]
    mean = rgb.mean(1, keepdims=True)
    d = rgb - mean
    lo, hi = rgb.min(1), rgb.max(1)
    axis = hi - lo
    # flip axis components that anti-correlate with the dominant channel
    dom = np.argmax(axis, 1)
    ddom = np.take_along_axis(d, dom[:, None, None].repeat(3, 2), 2)[..., 0]
    cov = (d * ddom[..., None]).sum(1)
    axis = np.where(cov < 0, -axis, axis)
    t = (d * axis[:, None, :]).sum(2)
    tmin, tmax = t.argmin(1), t.argmax(1)
    c0 = rgb[np.arange(n), tmax]
    c1 = rgb[np.arange(n), tmin]
    e0, e1 = _565(c0), _565(c1)
    # 4-colour mode needs e0 > e1; equal endpoints: index 0 everywhere
    swap = e0 < e1
    e0, e1 = np.where(swap, e1, e0), np.where(swap, e0, e1)
    p0, p1 = _unpack565(e0), _unpack565(e1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)  # (N, 4, 3)
    dist = ((rgb[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(3)  # (N, 16, 4)
    idx = dist.argmin(2).astype(np.uint32)
    idx = np.where((e0 == e1)[:, None], 0, idx)
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0:2] = e0.astype("<u2").view(np.uint8).reshape(n, 2)
    out[:, 2:4] = e1.astype("<u2").view(np.uint8).reshape(n, 2)
    out[:, 4:8] = bits.astype("<u4").view(np.uint8).reshape(n, 4)
    return out


def _alpha_blocks(a):
    """DXT5 alpha blocks (N, 16) float -> (N, 8) bytes (8-value mode, a0 > a1)."""
    n = a.shape[0]
    a0 = np.clip(np.round(a.max(1)), 0, 255)
    a1 = np.clip(np.round(a.min(1)), 0, 255)
    same = a0 == a1
    a0 = np.where(same & (a0 < 255), a0 + 1, a0)
    a1 = np.where(same & (a0 == a1), a1 - 1, a1)
    pal = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) / 7 for k in range(1, 7)], 1)  # (N, 8)
    idx = np.abs(a[:, :, None] - pal[:, None, :]).argmin(2).astype(np.uint64)
    bits = (idx << (3 * np.arange(16, dtype=np.uint64))).sum(1).astype(np.uint64)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0] = a0.astype(np.uint8)
    out[:, 1] = a1.astype(np.uint8)
    out[:, 2:8] = bits.astype("<u8").view(np.uint8).reshape(n, 8)[:, :6]
    return out


def _encode_level(img, fmt):
    b = _blocks(img.astype(np.float32))
    if fmt in (19, 25):
        return _colour_blocks(b[..., :3]).tobytes()
    colour = _colour_blocks(b[..., :3])
    alpha = _alpha_blocks(b[..., 3])
    return np.concatenate([alpha, colour], 1).tobytes()


def _down(img):
    h, w, c = img.shape
    return img.reshape(h // 2, 2, w // 2, 2, c).astype(np.float32).mean((1, 3))


def prepare(rgba, kind):
    """rgba uint8 (H, W, 4) in the usual layout -> (array in the game's channel layout, format)."""
    img = rgba.astype(np.float32)
    if kind == "nm":
        out = np.empty_like(img)
        out[..., 0] = 255
        out[..., 1] = img[..., 1]   # Y
        out[..., 2] = 255
        out[..., 3] = img[..., 0]   # X
        return out, KINDS["nm"]
    if kind == "bm" and (img[..., 3] < 250).any():
        return img, KINDS["bma"]
    return img, KINDS[kind]


def encode(rgba, kind, mips=None):
    """uint8 (H, W, 4) -> rTexture bytes"""
    h, w = rgba.shape[:2]
    if h & (h - 1) or w & (w - 1) or h < 4 or w < 4:
        raise ValueError(f"{w} x {h}: width and height must be powers of two, at least 4")
    img, fmt = prepare(rgba, kind)
    full = 1
    while (w >> full) >= 4 and (h >> full) >= 4:
        full += 1
    mips = min(mips or full, full)
    levels = []
    cur = img
    for m in range(mips):
        levels.append(_encode_level(cur, fmt))
        if m + 1 < mips:
            cur = _down(cur)
    d2 = 2 | (mips << 4) | (1 << 9) | (w << 17)
    d3 = h | (1 << 13)
    head = b"TEX\0" + struct.pack("<HBB", 0x87, 0, 1) + struct.pack("<III", d2, d3, fmt)  # byte 7 is 1 in stock files
    table = 0x14 + 4 * mips
    offs, o = [], table
    for lv in levels:
        offs.append(o)
        o += len(lv)
    return head + struct.pack(f"<{mips}I", *offs) + b"".join(levels)


def main():
    import argparse
    from PIL import Image
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--kind", required=True, choices=["bm", "nm", "mm"])
    ap.add_argument("--mips", type=int)
    a = ap.parse_args()
    rgba = np.asarray(Image.open(a.src).convert("RGBA"))
    data = encode(rgba, a.kind, a.mips)
    open(a.dst, "wb").write(data)
    print(f"wrote {a.dst} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
