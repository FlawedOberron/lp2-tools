#!/usr/bin/env python3
"""Terrain areas (the map editor's terrain.gd) -> placeable pieces, added to the map as copies.

  lp2terrain.py build --game LP2_DIR PROJECT [ID]     build the project's terrain pieces (all, or one)

Project "terrains": [{"id", "name", "pos": [x, y, z] (cm: the grid's corner, cell (0, 0)), "cell": cm per cell,
"cells": [nx, nz], "heights" / "weights" / "holes": its files, "material": the base layer's project material
("" = blockout), "tile": metres per texture repeat, "layers": up to 4 paint layers [{material, tile}]}].
  terrain/<id>.r32   (nx + 1) * (nz + 1) little-endian float32 heights (cm above pos y), rows along x, one per z
  terrain/<id>.w8    4 bytes per height point: paint layers 1-4's weights (the base has what they leave of 255)
  terrain/<id>.hole  1 byte per cell, rows along x: 1 = a hole (no ground, no collision)
Missing files: flat, unpainted, no holes. A paint layer's "slope": {on, min, max, soft} (degrees) also lays it on
every point that steep, live (effective: the layer raised to rule_weight, then all scaled back to 255; the editor's
terrain._effective alike).
Sharp (default): each cell takes its strongest layer (cell_layers, as the editor's terrain.cell_layer) and is built
with that layer's material, so the borders follow the cells. "blend": true: the blended layers are baked
(bake_parts) into colour / normal / mask textures per chunk of up to 1024 px at "bake_px" pixels per metre,
project materials terrain_bake_<id>_<cx>_<cz>, so the blends are smooth (and softer close up than the tiled ones).

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


def rule_weight(deg, lo, hi, soft):
    if soft <= 0:
        return ((deg >= lo) & (deg <= hi)).astype(np.float64)
    return np.clip((deg - (lo - soft)) / soft, 0, 1) * np.clip(((hi + soft) - deg) / soft, 0, 1)


def effective(t, H, W):
    """the paint with the slope rules applied -> weights (nz+1, nx+1, 4) uint8"""
    rules = [(k, layer(t, k)["slope"]) for k in range(1, LAYERS)
             if isinstance(layer(t, k).get("slope"), dict) and layer(t, k)["slope"].get("on")]
    if not rules:
        return W
    gz, gx = np.gradient(H, float(t["cell"]))   # central differences, one-sided at the edges (as the editor)
    deg = np.degrees(np.arctan(np.hypot(gx, gz)))
    E = W.astype(np.float64)
    for k, r in rules:
        E[..., k - 1] = np.maximum(E[..., k - 1], rule_weight(deg, float(r.get("min", 35)), float(r.get("max", 90)),
                                                              float(r.get("soft", 5))) * 255.0)
    s = E.sum(-1, keepdims=True)
    E = np.where(s > 255.0, E * 255.0 / np.maximum(s, 1e-9), E)
    return np.clip(np.floor(E + 0.5), 0, 255).astype(np.uint8)


def _wrap_sample(img, u, v):
    """bilinear, wrapping: img (h, w, c) float at texture coordinates u, v (any shape) -> (..., c)"""
    h, w = img.shape[:2]
    x, y = u * w - 0.5, v * h - 0.5
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    x0, y0, x1, y1 = x0 % w, y0 % h, (x0 + 1) % w, (y0 + 1) % h
    return (img[y0, x0] * (1 - fx) + img[y0, x1] * fx) * (1 - fy) + (img[y1, x0] * (1 - fx) + img[y1, x1] * fx) * fy


def _layer_images(project, mname, tile, px):
    """a layer material's colour / normal / mask, each resized to tile * px pixels a side -> {kind: float array}"""
    from PIL import Image
    m = lp2mesh.load_material(project, mname) or {}
    n = max(4, int(round(tile * px)))
    out = {}
    for kind, flat in (("bm", None), ("nm", (128, 128, 255)), ("mm", (0, 0, 0))):
        if m.get(kind):
            im = Image.open(os.path.join(lp2mesh.mat_dir(project, mname), m[kind])).convert("RGBA").resize((n, n), Image.LANCZOS)
            out[kind] = np.asarray(im, np.float64)
        else:
            c = flat or tuple(int(round(255 * min(1.0, max(0.0, x)))) for x in m.get("colour", (0.8, 0.8, 0.8)))
            out[kind] = np.array([[[*c, 255]]], np.float64)
    return out


def bake_parts(project, t, H, E, O, log=print):
    """the smooth blend: chunks of cells, each with its own baked material (UVs 0..1 over the chunk)
    -> (parts, {part material key: project material})"""
    from PIL import Image
    nz, nx = O.shape
    cm = float(t["cell"]) / 100.0               # metres per cell
    px = float(t.get("bake_px", 16.0))
    per = max(1, int(1024 // (px * cm)))         # cells per chunk side
    x0, _, z0 = (float(v) / 100.0 for v in t["pos"])
    lays = {k: material(project, t, k) for k in range(LAYERS)}
    imgs = {}
    parts, slots = [], {}
    w_full = np.concatenate([np.maximum(255 - E.astype(np.int32).sum(-1, keepdims=True), 0), E.astype(np.int32)], -1) / 255.0
    for cz in range(0, nz, per):
        for cx in range(0, nx, per):
            cells = np.zeros_like(O)
            cells[cz:cz + per, cx:cx + per] = True
            cells &= ~O
            if not cells.any():
                continue
            wc, dc = min(per, nx - cx), min(per, nz - cz)   # cells
            T = lp2mesh.pot(int(np.ceil(max(wc, dc) * cm * px)), 1024)
            g = (np.arange(T) + 0.5) / T
            gx, gz = np.meshgrid(cx + g * wc, cz + g * dc)   # grid units (cells) at the texel centres
            ix, iz = np.clip(np.floor(gx).astype(int), 0, nx - 1), np.clip(np.floor(gz).astype(int), 0, nz - 1)
            fx, fz = (gx - ix)[..., None], (gz - iz)[..., None]
            wt = (w_full[iz, ix] * (1 - fx) + w_full[iz, ix + 1] * fx) * (1 - fz) + \
                 (w_full[iz + 1, ix] * (1 - fx) + w_full[iz + 1, ix + 1] * fx) * fz   # (T, T, 5)
            wt /= np.maximum(wt.sum(-1, keepdims=True), 1e-9)
            wx, wz = x0 + gx * cm, z0 + gz * cm   # world metres
            out = {k: np.zeros((T, T, 4)) for k in lp2mesh.KINDS}
            for k in range(LAYERS):
                if wt[..., k].max() <= 0:
                    continue
                mname, tile = lays[k]
                if (mname, tile) not in imgs:
                    imgs[(mname, tile)] = _layer_images(project, mname, tile, px)
                for kind, im in imgs[(mname, tile)].items():
                    out[kind] += _wrap_sample(im, wx / tile, wz / tile) * wt[..., k:k + 1]
            nm = out["nm"][..., :3] / 127.5 - 1.0   # blended normals: unit length again
            nm /= np.maximum(np.linalg.norm(nm, axis=-1, keepdims=True), 1e-6)
            out["nm"][..., :3] = (nm + 1.0) * 127.5
            name = f"terrain_bake_{t['id']}_{cx // per}_{cz // per}"
            d = lp2mesh.mat_dir(project, name)
            os.makedirs(d, exist_ok=True)
            for kind in lp2mesh.KINDS:
                Image.fromarray(np.clip(out[kind] + 0.5, 0, 255).astype(np.uint8)).save(os.path.join(d, kind + ".png"))
            lp2mesh.save_material(project, name, {"bm": "bm.png", "nm": "nm.png", "mm": "mm.png", "colour": [1, 1, 1], "size": T})
            part = grid_mesh(t, H, cells, 1.0, 0)
            P = part["P"]   # UVs 0..1 across the chunk
            part["U"] = np.stack([(P[:, 0] - (x0 + cx * cm)) / (wc * cm), (P[:, 2] - (z0 + cz * cm)) / (dc * cm)], -1)
            part["mat"] = f"chunk{cx // per}_{cz // per}"
            parts.append(part)
            slots[part["mat"]] = name
    log(f"  terrain {t.get('name') or t['id']}: smooth blend baked, {len(parts)} chunk(s) of up to {per} cells at {px:g} px/m")
    return parts, slots


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
    E = effective(t, H, W)
    L = cell_layers(E)
    used = [k for k in range(LAYERS) if (~O & (L == k)).any()]
    if not used:
        raise SystemExit(f"terrain {t.get('name') or tid}: every cell is a hole")
    mats = {k: material(project, t, k) for k in (range(LAYERS) if t.get("blend") else used)}
    key = build_key(project, t, [m for m, _ in mats.values()])
    kp = os.path.join(d, "build.key")
    if os.path.exists(kp) and open(kp).read() == key and os.path.exists(os.path.join(d, "project.json")):
        return json.load(open(os.path.join(d, "import.json")))
    os.makedirs(d, exist_ok=True)
    if t.get("blend"):
        parts, slots = bake_parts(project, t, H, E, O, log)
    else:
        parts = [grid_mesh(t, H, ~O & (L == k), mats[k][1], k) for k in used]
        slots = {f"layer{k}": mats[k][0] for k in used}
    json.dump({"source": f"terrain {tid}", "collision": "mesh", "scale": 100.0, "slots": slots},
              open(os.path.join(d, "import.json"), "w"), indent=1)
    cfg = lp2mesh.build_import(game, project, t.get("name") or tid, log, d=d, mesh=(parts, {}))
    open(kp, "w").write(key)
    return cfg


def layer_damage(t, k):
    """a layer's damage over time ({player, vs, player_kill, vs_kill}, the volumes' "damage"), or None"""
    q = t.get("damage") if k == 0 else layer(t, k).get("damage")
    if isinstance(q, dict) and (float(q.get("player", 0)) > 0 or float(q.get("vs", 0)) > 0 or q.get("player_kill") or q.get("vs_kill")):
        return q
    return None


def damage_volumes(project, p, log=print, spread=300.0, above=150.0, below=100.0, cap=200):
    """map.json damage_volumes for terrain layers with "damage": the cells where such a layer is the strongest (holes
    out), merged into rectangles whose ground varies by at most `spread` cm, each a box from `below` cm under its
    lowest corner to `above` cm over its highest (a character's position is its feet)"""
    out = []
    for t in p.get("terrains") or []:
        ks = [k for k in range(LAYERS) if layer_damage(t, k)]
        if not ks:
            continue
        H, W, O = grids(project, t)
        L = cell_layers(effective(t, H, W))
        nz, nx = L.shape
        cell = float(t["cell"])
        x0, y0, z0 = (float(v) for v in t["pos"])
        lo4 = np.minimum(np.minimum(H[:-1, :-1], H[:-1, 1:]), np.minimum(H[1:, :-1], H[1:, 1:]))
        hi4 = np.maximum(np.maximum(H[:-1, :-1], H[:-1, 1:]), np.maximum(H[1:, :-1], H[1:, 1:]))
        n0 = len(out)
        for k in ks:
            q = layer_damage(t, k)
            free = ~O & (L == k)
            for iz in range(nz):
                ix = 0
                while ix < nx:
                    if not free[iz, ix]:
                        ix += 1
                        continue
                    lo, hi = lo4[iz, ix], hi4[iz, ix]
                    jx = ix + 1   # grow along x
                    while jx < nx and free[iz, jx] and max(hi, hi4[iz, jx]) - min(lo, lo4[iz, jx]) <= spread:
                        lo, hi = min(lo, lo4[iz, jx]), max(hi, hi4[iz, jx])
                        jx += 1
                    jz = iz + 1   # then down whole rows
                    while jz < nz and free[jz, ix:jx].all():
                        l2, h2 = min(lo, lo4[jz, ix:jx].min()), max(hi, hi4[jz, ix:jx].max())
                        if h2 - l2 > spread:
                            break
                        lo, hi = l2, h2
                        jz += 1
                    free[iz:jz, ix:jx] = False
                    e = dict(min=[round(float(x), 1) for x in (x0 + ix * cell, y0 + lo - below, z0 + iz * cell)],
                             max=[round(float(x), 1) for x in (x0 + jx * cell, y0 + hi + above, z0 + jz * cell)],
                             player=float(q.get("player", 0)), vs=float(q.get("vs", 0)))
                    for f in ("player_kill", "vs_kill"):
                        if q.get(f):
                            e[f] = True
                    out.append(e)
                    ix = jx
        log(f"  terrain {t.get('name') or t['id']}: {len(out) - n0} damage box(es)")
    if len(out) > cap:
        log(f"  WARNING: {len(out)} terrain damage boxes, only the first {cap} kept (larger cells or flatter ground merge better)")
        out = out[:cap]
    return out


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
