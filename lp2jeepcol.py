#!/usr/bin/env python3
"""Ground for the jeep test: an LP1/LP2 SBC1 collision file (move.sbc1) -> the triangle file the xlive DLL's jeep
driver raycasts against (src/mods/jeep_drive.cpp).

  lp2jeepcol.py move.sbc1 OUT.col

OUT.col: "JCOL", u32 version 1, u32 triangle count, then per triangle 9 little-endian floats (3 corners, cm, game
axes). Every triangle of the file is kept (invisible walls included: the jeep shouldn't leave the map either).
The DLL loads <game>\\Mods\\jeep\\online<NN>.col for online map NN (NN two digits)."""
import struct
import sys

import lp2col


def convert(src, dst):
    groups = lp2col.read_sbc1(open(src, "rb").read())
    tris = []
    for g in groups:
        v = g["verts"]
        for (a, b, c), _surface in g["tris"]:
            if a == b or b == c or a == c:
                continue
            tris.append(v[a] + v[b] + v[c])
    with open(dst, "wb") as f:
        f.write(b"JCOL" + struct.pack("<II", 1, len(tris)))
        for t in tris:
            f.write(struct.pack("<9f", *t))
    return len(tris)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(f"{convert(sys.argv[1], sys.argv[2])} triangles -> {sys.argv[2]}")
