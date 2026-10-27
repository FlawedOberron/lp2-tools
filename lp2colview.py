#!/usr/bin/env python3
"""A project's collision as the export builds it (the LP1 file plus the editor's moved / hidden / copied pieces,
lp2pieces.apply_collision, and other maps' copied pieces), for the editor's View collision.

  lp2colview.py PROJECT_DIR OUT.bin [--kind move|bullet] [--library LIB] [--geometry FILE]

--geometry: the editor's unsaved level geometry (geometry.json format) instead of the project's file.

OUT.bin: u32 triangle count, then per triangle 3 x (x, y, z) f32 in cm, then per triangle u32 surface, then per
triangle i32 owner: the stage atom it belongs to, -1000000 - k for collision-only wall k (no visible geometry near:
invisible boundaries), or -2 - k for the geometry's copy k (the editor selects what it belongs to).
move = what players walk on (lp1_move, atari); bullet = what shots hit (lp1_bullet, tama).
Needs the stage preview (.preview/stage, lp2preview.py) when the geometry is edited.
"""
import argparse, json, os, struct, sys

import lp2col, lp2pieces, lp2project


def stage_model(folder):
    for d, _, fs in os.walk(os.path.join(folder, ".preview", "stage")):
        if "online00.rModel" in fs:
            return os.path.join(d, "online00.rModel")
    raise SystemExit("no stage preview (.preview/stage): rebuild the preview")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("out")
    ap.add_argument("--kind", choices=("move", "bullet"), default="move")
    ap.add_argument("--library")
    ap.add_argument("--geometry")
    a = ap.parse_args()
    folder = os.path.abspath(a.project)
    p = json.load(open(os.path.join(folder, "project.json")))
    key = "lp1_" + a.kind
    src = (p.get("collision") or {}).get(key)
    if not src:
        raise SystemExit(f"project.json has no collision.{key}")
    groups = lp2col.read_sbc1(open(lp2project.path(folder, src), "rb").read())
    gpath = a.geometry or (os.path.join(folder, p["geometry"]["file"]) if p.get("geometry") else None)
    geo = lp2pieces.load_geometry(gpath) if gpath else {}
    note = "as imported"
    S = lp2pieces.read_stage(stage_model(folder))
    per_mesh, n = lp2pieces.atoms(S)
    groups, (mv, dr, cp) = lp2pieces.apply_collision(groups, S, per_mesh, n, geo)   # also each triangle's owner
    if lp2pieces.edited(geo):
        note = f"{mv} triangles moved, {dr} dropped, {cp} copied"
        if a.library and lp2pieces.foreign_copies(geo):
            groups += lp2pieces.foreign_collision(a.library, geo, key, folder)
    pos, surf, owner = [], [], []
    for g in groups:
        V = g["verts"]
        own = list(g.get("own") or [-1] * len(g["tris"]))
        for ((i, j, k), s), o in zip(g["tris"], own):
            pos.extend(V[i]); pos.extend(V[j]); pos.extend(V[k])
            surf.append(s)
            owner.append(int(o))
    walls = len({o for o in owner if o <= lp2pieces.WALL})
    with open(a.out, "wb") as f:
        f.write(struct.pack("<I", len(surf)))
        f.write(struct.pack(f"<{len(pos)}f", *pos))
        f.write(struct.pack(f"<{len(surf)}I", *surf))
        f.write(struct.pack(f"<{len(owner)}i", *owner))
    print(f"{a.kind} collision: {len(surf)} triangles ({note}), {walls} collision-only walls")


if __name__ == "__main__":
    sys.exit(main())
