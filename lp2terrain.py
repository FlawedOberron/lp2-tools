#!/usr/bin/env python3
"""Terrain areas (the map editor's terrain.gd) -> placeable pieces, added to the map as copies.

  lp2terrain.py build --game LP2_DIR PROJECT [ID]     build the project's terrain pieces (all, or one)

Project "terrains": [{"id", "name", "pos": [x, y, z] (cm: the grid's corner, cell (0, 0)), "cell": cm per cell,
"cells": [nx, nz], "heights" / "weights" / "holes": its files, "material": the base layer's project material
("" = blockout), "tile": metres per texture repeat, "layers": up to 4 paint layers [{material, tile}]}].
  terrain/<id>.r32   (nx + 1) * (nz + 1) little-endian float32 heights (cm above pos y), rows along x, one per z
  terrain/<id>.w8    4 bytes per height point: paint layers 1-4's weights (the base has what they leave of 255)
  terrain/<id>.hole  1 byte per cell, rows along x: 1 = a hole (no ground, no collision)
Missing files: flat, unpainted, no holes. Each cell takes its strongest layer (cell_layers, as the editor's
terrain.cell_layer) and is built with that layer's material, so the borders follow the cells.

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
# a layer without a material: the blockout grid in its own colour (the editor's terrain.LAYER_COLOURS)
BLOCKOUT_COLOURS = [(0.42, 0.55, 0.3), (0.76, 0.66, 0.45), (0.5, 0.5, 0.52), (0.92, 0.94, 0.97), (0.45, 0.32, 0.22)]
LAYERS = 5
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def _grid_file(project, t, key, ext):
    return os.path.join(project, *str(t.get(key) or f"terrain/{t['id']}.{ext}").split("/"))


def grids(project, t):
    """-> heights (nz+1, nx+1) cm, weights (nz+1, nx+1, 4) uint8, holes (nz, nx) bool"""
    nx, nz = (int(x) for x in t["cells"])
    H, W, O = np.zeros((nz + 1, nx + 1)), np.zeros((nz + 1, nx + 1, 4), np.uint8), np.zeros((nz, nx), bool)
    p = _grid_file(project, t, "heights", "r32")
    if os.path.exists(p) and os.path.getsize(p) == H.size * 4:
        H = np.fromfile(p, "<f4").reshape(H.shape).astype(np.float64)
    p = _grid_file(project, t, "weights", "w8")
    if os.path.exists(p) and os.path.getsize(p) == W.size:
        W = np.fromfile(p, np.uint8).reshape(W.shape)
    p = _grid_file(project, t, "holes", "hole")
    if os.path.exists(p) and os.path.getsize(p) == O.size:
        O = np.fromfile(p, np.uint8).reshape(O.shape) > 0
    return H, W, O


def heights(project, t):
    return grids(project, t)[0]


def cell_layers(W):
    """each cell's strongest layer from its four corners (base = 255 minus the paint layers); ties: the lower layer"""
    w = W.astype(np.int32)
    full = np.concatenate([np.maximum(255 - w.sum(-1, keepdims=True), 0), w], -1)   # (nz+1, nx+1, 5)
    s = full[:-1, :-1] + full[:-1, 1:] + full[1:, :-1] + full[1:, 1:]
    return np.argmax(s, -1)


def layer(t, k):
    if k == 0:
        return {"material": t.get("material") or "", "tile": float(t.get("tile", 4.0))}
    ls = t.get("layers") or []
    return ls[k - 1] if k - 1 < len(ls) else {"material": "", "tile": 4.0}


def material(project, t, k=0):
    """layer k's project material, its blockout one made when it has none -> (name, metres per texture repeat)"""
    li = layer(t, k)
    name = li.get("material") or ""
    if name and lp2mesh.load_material(project, name):
        return name, float(li.get("tile", 4.0))
    bname = BLOCKOUT if k == 0 else f"{BLOCKOUT}_{k}"
    if not lp2mesh.load_material(project, bname):
        from PIL import Image
        d = lp2mesh.mat_dir(project, bname)
        os.makedirs(d, exist_ok=True)
        Image.fromarray(lp2mesh.blockout_image(BLOCKOUT_COLOURS[k])).save(os.path.join(d, "bm.png"))
        lp2mesh.save_material(project, bname, {"colour": list(BLOCKOUT_COLOURS[k]), "bm": "bm.png"})
    return bname, 1.0   # the blockout tile is 1 m


def grid_mesh(t, H, cells, tile, k):
    """the cells' triangles (a boolean (nz, nx) mask) -> one part (lp2mesh read_* layout, metres, map space)"""
    nz, nx = H.shape[0] - 1, H.shape[1] - 1
    cell = float(t["cell"])
    x0, y0, z0 = (float(v) for v in t["pos"])
    iz, ix = np.nonzero(cells)
    a = iz * (nx + 1) + ix
    b, c, d = a + 1, a + nx + 1, a + nx + 2   # (ix+1, iz), (ix, iz+1), (ix+1, iz+1)
    T = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])   # wound to face up (+y)
    used, inv = np.unique(T, return_inverse=True)
    gz, gx = np.divmod(used, nx + 1)
    P = np.stack([x0 + gx * cell, y0 + H.ravel()[used], z0 + gz * cell], -1) / 100.0
    U = np.stack([P[:, 0], P[:, 2]], -1) / tile
    return dict(obj=t.get("name", "Terrain"), mat=f"layer{k}", P=P, N=None, U=U, C=None, T=inv.reshape(-1, 3))


def build_key(project, t, mnames):
    h = hashlib.sha1(json.dumps(t, sort_keys=True).encode())
    for key, ext in (("heights", "r32"), ("weights", "w8"), ("holes", "hole")):
        p = _grid_file(project, t, key, ext)
        if os.path.exists(p):
            h.update(key.encode() + open(p, "rb").read())
    for mname in mnames:
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
    H, W, O = grids(project, t)
    L = cell_layers(W)
    used = [k for k in range(LAYERS) if (~O & (L == k)).any()]
    if not used:
        raise SystemExit(f"terrain {t.get('name') or tid}: every cell is a hole")
    mats = {k: material(project, t, k) for k in used}
    key = build_key(project, t, [m for m, _ in mats.values()])
    kp = os.path.join(d, "build.key")
    if os.path.exists(kp) and open(kp).read() == key and os.path.exists(os.path.join(d, "project.json")):
        return json.load(open(os.path.join(d, "import.json")))
    os.makedirs(d, exist_ok=True)
    json.dump({"source": f"terrain {tid}", "collision": "mesh", "scale": 100.0,
               "slots": {f"layer{k}": mats[k][0] for k in used}}, open(os.path.join(d, "import.json"), "w"), indent=1)
    parts = [grid_mesh(t, H, ~O & (L == k), mats[k][1], k) for k in used]
    cfg = lp2mesh.build_import(game, project, t.get("name") or tid, log, d=d, mesh=(parts, {}))
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
