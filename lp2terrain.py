#!/usr/bin/env python3
"""Terrain areas (the map editor's terrain.gd) -> placeable pieces, added to the map as copies.

  lp2terrain.py build --game LP2_DIR PROJECT [ID]     build the project's terrain pieces (all, or one)

Project "terrains": [{"id", "name", "pos": [x, y, z] (cm: the grid's corner, cell (0, 0)), "cell": cm per cell,
"cells": [nx, nz], "heights": "terrain/<id>.r32", "material": project material ("" = blockout), "tile": metres per
texture repeat}]. The .r32 holds (nx + 1) * (nz + 1) little-endian float32 heights (cm above pos y), rows along x,
one row per z: h[iz * (nx + 1) + ix]; a missing file is flat.

A terrain is built like a mesh import (lp2mesh.build_import with its triangles made here) into PROJECT/terrain/<id>/,
then placed through the foreign-copy path as "@project/terrain/<id>" with an identity matrix (the piece is built in
map space), so textures, collision (its own triangles), the light bake and the stage limits come for free.
"""
import argparse, hashlib, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2mesh  # noqa: E402

BLOCKOUT = "terrain_blockout"
BLOCKOUT_GREEN = (0.42, 0.55, 0.3)
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def heights(project, t):
    nx, nz = (int(x) for x in t["cells"])
    p = os.path.join(project, *str(t.get("heights", "")).split("/")) if t.get("heights") else ""
    if p and os.path.exists(p):
        h = np.fromfile(p, "<f4")
        if len(h) == (nx + 1) * (nz + 1):
            return h.reshape(nz + 1, nx + 1).astype(np.float64)
    return np.zeros((nz + 1, nx + 1))


def material(project, t):
    """the terrain's project material, the blockout one made when missing -> (name, metres per texture repeat)"""
    name = t.get("material") or ""
    if name and lp2mesh.load_material(project, name):
        return name, float(t.get("tile", 4.0))
    if not lp2mesh.load_material(project, BLOCKOUT):
        from PIL import Image
        d = lp2mesh.mat_dir(project, BLOCKOUT)
        os.makedirs(d, exist_ok=True)
        Image.fromarray(lp2mesh.blockout_image(BLOCKOUT_GREEN)).save(os.path.join(d, "bm.png"))
        lp2mesh.save_material(project, BLOCKOUT, {"colour": list(BLOCKOUT_GREEN), "bm": "bm.png"})
    return BLOCKOUT, 1.0   # its tile is 1 m


def grid_mesh(t, H, tile):
    """the height grid -> one part (lp2mesh read_* layout, metres, map space)"""
    nz, nx = H.shape[0] - 1, H.shape[1] - 1
    cell = float(t["cell"])
    x0, y0, z0 = (float(v) for v in t["pos"])
    iz, ix = np.mgrid[0:nz + 1, 0:nx + 1]
    P = np.stack([x0 + ix * cell, y0 + H, z0 + iz * cell], -1).reshape(-1, 3) / 100.0
    U = np.stack([P[:, 0], P[:, 2]], -1) / tile
    k = (iz[:-1, :-1] * (nx + 1) + ix[:-1, :-1]).ravel()
    a, b, c, d = k, k + 1, k + nx + 1, k + nx + 2   # (ix, iz), (ix+1, iz), (ix, iz+1), (ix+1, iz+1)
    T = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])   # wound to face up (+y)
    return dict(obj=t.get("name", "Terrain"), mat="terrain", P=P, N=None, U=U, C=None, T=T)


def build_key(project, t, mname):
    h = hashlib.sha1(json.dumps(t, sort_keys=True).encode())
    hp = os.path.join(project, *str(t.get("heights", "")).split("/")) if t.get("heights") else ""
    if hp and os.path.exists(hp):
        h.update(open(hp, "rb").read())
    m = lp2mesh.load_material(project, mname) or {}
    h.update(json.dumps(m, sort_keys=True).encode())
    for k in lp2mesh.KINDS:
        if m.get(k):
            st = os.stat(os.path.join(lp2mesh.mat_dir(project, mname), m[k]))
            h.update(f"{k}:{st.st_size}:{st.st_mtime_ns}".encode())
    for f in ("lp2terrain.py", "lp2mesh.py", "lp2stage.py", "lp2col.py"):
        h.update(open(os.path.join(HERE, f), "rb").read())
    return h.hexdigest()


def build(game, project, t, log=print):
    """the terrain's piece in PROJECT/terrain/<id>/ (skipped while nothing it is made from changed) -> import.json"""
    tid = t["id"]
    d = os.path.join(project, "terrain", tid)
    mname, tile = material(project, t)
    key = build_key(project, t, mname)
    kp = os.path.join(d, "build.key")
    if os.path.exists(kp) and open(kp).read() == key and os.path.exists(os.path.join(d, "project.json")):
        return json.load(open(os.path.join(d, "import.json")))
    os.makedirs(d, exist_ok=True)
    json.dump({"source": f"terrain {tid}", "collision": "mesh", "scale": 100.0, "slots": {"terrain": mname}},
              open(os.path.join(d, "import.json"), "w"), indent=1)
    H = heights(project, t)
    cfg = lp2mesh.build_import(game, project, t.get("name") or tid, log, d=d, mesh=([grid_mesh(t, H, tile)], {}))
    open(kp, "w").write(key)
    return cfg


def add_copies(game, project, p, geo, log=print):
    """build the project's terrains and place them in geo (the geometry edits) as copies -> geo"""
    ts = p.get("terrains") or []
    if not ts:
        return geo
    geo = dict(geo or {})
    copies = list(geo.get("copies") or [])
    for t in ts:
        cfg = build(game, project, t, log)
        rev = open(os.path.join(project, "terrain", t["id"], "build.key")).read()[:12]
        copies += [{"map": f"@project/terrain/{t['id']}", "atom": a, "m": IDENTITY, "rev": rev}
                   for a in range(int(cfg["atoms"]))]
        log(f"  terrain {t.get('name') or t['id']}: {int(t['cells'][0])} x {int(t['cells'][1])} cells of "
            f"{float(t['cell']) / 100:g} m, {cfg['triangles']} triangles")
    geo["copies"] = copies
    return geo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--game", required=True)
    b.add_argument("project")
    b.add_argument("id", nargs="?")
    a = ap.parse_args()
    p = json.load(open(os.path.join(a.project, "project.json")))
    for t in p.get("terrains") or []:
        if a.id in (None, t["id"]):
            cfg = build(a.game, a.project, t)
            print(f"{t['id']}: {cfg['triangles']} triangles, {cfg['atoms']} atoms")


if __name__ == "__main__":
    main()
