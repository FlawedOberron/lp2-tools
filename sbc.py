#!/usr/bin/env python3
"""Lost Planet 2 rCollision (MT 'SBC\\xff') reader -> OBJ, one object per group, one material
per surface type.

  sbc.py IN.rCollision [OUT.obj]       one file
  sbc.py -r DIR                        every *.rCollision under DIR, .obj written alongside

Maps have two: atari<map> (movement; 'atari' = hit) and tama<map> (bullets; 'tama' = bullet).

Layout (little-endian), from atarionline00 (1.7 MB):
  0x00 'SBC\\xff'  u32 version 2009052600  u16 groups  u16 surface types  u32 triangles  u32 vertices
  0x20 bounds: vec4 min, vec4 max
  0x40 groups x 48 bytes: vec4 min, vec4 max, u32 runtime, u32 first triangle, u32 first vertex, u32 -1
  then triangles x 32 bytes: f32 normal xyz, u16 v0 v1 v2 (relative to the group's first vertex),
       u16 surface type, 12 bytes 0 (no plane distance)
  then vertices x 16 bytes: f32 xyz, 0
  then surface types x 32 bytes: u32 flags (e.g. 0x19f8f6ff, 0x40002000), u32[2] 0, u32 0xff,
       u32 0, u32[3] hash-like constants
  then 'BVHC' chunks, one per group plus one over the groups: 'BVHC' u32 2008120100 u32 1 u32 0,
       vec4 min, vec4 max, u32 nodes, u32 triangles, u32[2] 0, u16 leaf order, then nodes x 112
       bytes (lp2col.py documents and writes them). Not needed to read the mesh.
"""
import os, struct, sys

MAGIC = b"SBC\xff"


def read(b):
    if b[:4] != MAGIC:
        raise ValueError("not an SBC collision file")
    ver, ngroups, nsurf, ntris, nverts = struct.unpack_from("<IHHII", b, 4)
    groups = []
    for g in range(ngroups):
        o = 0x40 + 48 * g
        first_tri, first_vert = struct.unpack_from("<II", b, o + 36)
        groups.append(dict(tri=first_tri, vert=first_vert))
    to = 0x40 + 48 * ngroups
    tris = [struct.unpack_from("<3f4H", b, to + 32 * i) for i in range(ntris)]
    vo = to + 32 * ntris
    verts = [struct.unpack_from("<3f", b, vo + 16 * i) for i in range(nverts)]
    so = vo + 16 * nverts
    surfaces = [struct.unpack_from("<I", b, so + 32 * i)[0] for i in range(nsurf)]
    for g, grp in enumerate(groups):
        grp["tri_end"] = groups[g + 1]["tri"] if g + 1 < ngroups else ntris
    return dict(version=ver, groups=groups, tris=tris, verts=verts, surfaces=surfaces)


def to_obj(col, out, name):
    mtl = os.path.splitext(out)[0] + ".mtl"
    colours = [(0.9, 0.3, 0.3), (0.3, 0.8, 0.3), (0.3, 0.4, 0.9), (0.9, 0.8, 0.2), (0.8, 0.3, 0.9),
               (0.2, 0.8, 0.8), (0.9, 0.5, 0.1), (0.6, 0.6, 0.6)]
    with open(mtl, "w") as f:
        for i, flags in enumerate(col["surfaces"]):
            r, g, b = colours[i % len(colours)]
            f.write(f"newmtl {name}_surf{i}_{flags:08x}\nKd {r} {g} {b}\nd 0.6\n\n")
    with open(out, "w") as f:
        f.write(f"# {name}: {len(col['groups'])} groups, {len(col['tris'])} triangles\nmtllib {os.path.basename(mtl)}\n")
        for v in col["verts"]:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        for gi, g in enumerate(col["groups"]):
            f.write(f"o {name}_group{gi:02d}\n")
            cur = None
            for t in col["tris"][g["tri"]:g["tri_end"]]:
                s = t[6]
                if s != cur:
                    f.write(f"usemtl {name}_surf{s}_{col['surfaces'][s]:08x}\n")
                    cur = s
                a, b_, c = (g["vert"] + t[k] + 1 for k in (3, 4, 5))
                f.write(f"f {a} {b_} {c}\n")


def convert(path, out=None):
    col = read(open(path, "rb").read())
    out = out or os.path.splitext(path)[0] + ".col.obj"
    to_obj(col, out, os.path.splitext(os.path.basename(path))[0])
    flags = ", ".join(f"{s:#010x}" for s in col["surfaces"])
    print(f"{out}: {len(col['groups'])} groups, {len(col['tris'])} triangles, surface flags {flags}")


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "-r":
        for d, _, fs in os.walk(a[1]):
            for fn in fs:
                if fn.endswith(".rCollision"):
                    convert(os.path.join(d, fn))
    elif 1 <= len(a) <= 2:
        convert(*a)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
