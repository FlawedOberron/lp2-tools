#!/usr/bin/env python3
"""Map thumbnail for the create-match menu: any picture -> thumbnail.rTexture for a map package.

  lp2thumb.py IN.(png|jpg) OUT.rTexture [--zoom Z] [--at X,Y]

Like the stock ones (aBattlePlayerCreate.arc, flash\\dds\\ID221_SC00_ID .. SC13): 512 x 512 DXT5, one mip,
the picture inside a centred circle 401 px across (hard edge), transparent outside.
--zoom: how much of the picture's short side the circle spans (default 1 = all of it; 1.5 = closer).
--at: the circle's centre in the picture as fractions (default 0.5,0.5).
"""
import argparse

import numpy as np
from PIL import Image

import lp2tex

SIZE, RADIUS = 512, 200.5


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--at", default="0.5,0.5")
    a = ap.parse_args()
    im = Image.open(a.src).convert("RGB")
    cx, cy = (float(v) for v in a.at.split(","))
    side = min(im.size) / a.zoom  # picture pixels across the circle
    x, y = cx * im.size[0], cy * im.size[1]
    box = (x - side / 2, y - side / 2, x + side / 2, y + side / 2)
    circle = im.resize((round(2 * RADIUS), round(2 * RADIUS)), Image.LANCZOS, box=box)
    rgba = np.zeros((SIZE, SIZE, 4), np.uint8)
    o = round(SIZE / 2 - RADIUS)
    rgba[o:o + circle.size[1], o:o + circle.size[0], :3] = np.asarray(circle)
    yy, xx = np.mgrid[:SIZE, :SIZE]
    rgba[..., 3] = np.where(np.hypot(yy - (SIZE - 1) / 2, xx - (SIZE - 1) / 2) <= RADIUS, 255, 0)
    rgba[rgba[..., 3] == 0, :3] = 0
    tex = bytearray(lp2tex.encode(rgba, "bma", mips=1))
    tex[7] = 0  # as the stock menu pictures (lp2tex writes 1, as the part textures)
    open(a.dst, "wb").write(tex)
    print(f"{a.dst}: {SIZE} x {SIZE} DXT5, circle from {[round(v) for v in box]} of {im.size}")


if __name__ == "__main__":
    main()
