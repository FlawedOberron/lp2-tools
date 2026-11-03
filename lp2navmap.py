#!/usr/bin/env python3
"""A project's bot navigation (the editor's Build navmesh): lp2navgen.py over the movement collision as the export
builds it (lp2colview.project_collision), limited to the playable area.

  lp2navmap.py PROJECT_DIR [--library LIB]

Playable area: the walkable regions connected to the layout's markers (spawns, pickups, VS, posts in every set),
through shared edges, short jumps and drops (LEDGE_GAP across, LEDGE_DROP up or down) or the grapple (GRAPPLE from
AIM_UP over an edge to another region's edge, in line of sight), above the kill floor, outside kill volumes and, when the project has map limits volumes ("limits"), inside one of them. The rest (roofs, outside ledges, sealed rooms, under the map) is dropped.

Writes PROJECT/assets/nav/List_<tag>.rAINavigationMeshList + Way_<tag>.rAIWayPoint and the editor's view
PROJECT/.preview/navmesh.bin: u32 triangle count, per triangle 3 x (x, y, z) f32 cm, then per triangle u8 (1 kept,
0 dropped: outside the playable area); .preview/navmesh.json (and "@result"): the files (project-relative) and counts,
which the editor puts in project.json "navmesh".
"""
import argparse, json, math, os, struct, sys

import numpy as np

import lp2colview, lp2mapc, lp2navgen

LEDGE_GAP = 100.0 + 2 * lp2navgen.AGENT["radius"]   # cm across between two regions' edges that still connect
                                                     # them (a 1 m jump; both edges are held back by the radius)
LEDGE_DROP = 300.0   # cm up or down (one-way drops count both ways: regions are joined, not routed)
GRAPPLE = 1100.0     # the grapple's reach (uWp00 mRange, set to 1100.0 in its constructor, DX9 0xc76690 from
                     # 0x1379eb4: the aim ray's length, i.e. the crosshair turning green)
GRAPPLE_TRIES = 40   # grapple line-of-sight tests per pair of regions
AIM_UP = 150.0       # cm above the floor the grapple is fired from
SEED_BELOW = 300.0   # a marker's region: under it by up to this (markers sit a little above the floor)
SEED_ABOVE = 100.0


def collision(folder, library):
    groups, note = lp2colview.project_collision(folder, "move", library)
    verts, tris, base = [], [], 0
    for g in groups:
        verts.append(np.asarray(g["verts"], np.float32).reshape(-1, 3))
        tris.append(np.array([t for t, _ in g["tris"]], np.int64).reshape(-1, 3) + base)
        base += len(verts[-1])
    return np.concatenate(verts), np.concatenate(tris), note


def markers(folder, p):
    lay = json.load(open(os.path.join(folder, p["layout"]["file"])))
    out = []
    for s in lay.get("sets", []):
        for q in s.get("points", []) + s.get("objects", []):
            if "pos" in q:
                out.append(q["pos"])
    return np.array(out, np.float64).reshape(-1, 3)


def _find(parent, i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent, a, b):
    a, b = _find(parent, a), _find(parent, b)
    if a != b:
        parent[max(a, b)] = min(a, b)


def regions(v, p, verts=None, tris=None):
    """polygons joined across shared edges, then regions joined by jumps and the grapple (between open-edge
    vertices; the grapple needs a clear line through the collision verts / tris) -> region id per polygon"""
    n = len(p)
    parent = list(range(n))
    edges = {}
    for i, t in enumerate(p):
        for e in range(3):
            a, b = int(t[e]), int(t[(e + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append(i)
    for ps in edges.values():
        for j in ps[1:]:
            _union(parent, ps[0], j)
    open_v = {}
    for (a, b), ps in edges.items():
        if len(ps) == 1:
            open_v.setdefault(a, ps[0])
            open_v.setdefault(b, ps[0])
    if not open_v:
        return np.array([_find(parent, i) for i in range(n)])
    ids = np.array(list(open_v.keys()))
    poly = np.array([open_v[i] for i in ids])
    P = v[ids].astype(np.float64)
    cell = np.floor(P[:, [0, 2]] / GRAPPLE).astype(np.int64)
    grid = {}
    for k, c in enumerate(map(tuple, cell)):
        grid.setdefault(c, []).append(k)
    if verts is not None:
        V = verts.astype(np.float64)
        A, E1, E2 = V[tris[:, 0]], V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]]
    tried = {}   # attempts per region pair (the first in reach may be blocked, a later one clear)
    for k, (cx, cz) in enumerate(cell):
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for m in grid.get((cx + dx, cz + dz), ()):
                    if m <= k:
                        continue
                    ra, rb = _find(parent, int(poly[k])), _find(parent, int(poly[m]))
                    if ra == rb:
                        continue
                    d = P[m] - P[k]
                    flat, up = math.hypot(d[0], d[2]), abs(d[1])
                    if flat <= LEDGE_GAP and up <= LEDGE_DROP:   # a jump or a drop
                        _union(parent, ra, rb)
                        continue
                    if verts is None or tried.get((ra, rb), 0) >= GRAPPLE_TRIES:
                        continue
                    # the grapple: from the lower edge, aimed at the higher one, within reach and in sight
                    lo, hi = (P[k], P[m]) if P[k][1] <= P[m][1] else (P[m], P[k])
                    o = lo + [0, AIM_UP, 0]
                    to = hi   # the lip: the anchor hits the wall just under it and the climb does the rest
                    seg = to - o
                    dist = float(np.linalg.norm(seg))
                    if dist > GRAPPLE or dist < 1:
                        continue
                    tried[(ra, rb)] = tried.get((ra, rb), 0) + 1
                    if not lp2navgen.ray_hits(A, E1, E2, o, seg / dist, dist - 30):
                        _union(parent, ra, rb)
    return np.array([_find(parent, i) for i in range(n)])


def seed_polys(v, p, pts):
    """per marker: the polygon under it (its x / z inside, the floor SEED_BELOW under to SEED_ABOVE over it), else
    the nearest centroid within 3 m"""
    a, b, c = v[p[:, 0]], v[p[:, 1]], v[p[:, 2]]
    cen = v[p].mean(1)
    d = (b[:, 2] - c[:, 2]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 2] - c[:, 2])
    ok = np.abs(d) > 1e-6
    d = np.where(ok, d, 1)
    out = []
    for x, y, z in pts:
        l1 = ((b[:, 2] - c[:, 2]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (z - c[:, 2])) / d
        l2 = ((c[:, 2] - a[:, 2]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (z - c[:, 2])) / d
        l3 = 1 - l1 - l2
        h = l1 * a[:, 1] + l2 * b[:, 1] + l3 * c[:, 1]
        hit = ok & (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3) & (h >= y - SEED_BELOW) & (h <= y + SEED_ABOVE)
        if hit.any():
            out.append(int(np.flatnonzero(hit)[np.argmin(np.abs(h[hit] - y))]))
            continue
        dist = np.linalg.norm(cen - [x, y, z], axis=1)
        if dist.min() <= 300:
            out.append(int(dist.argmin()))
    return out


def in_volumes(p_json, pts, test):
    """per point: inside any of the volumes' boxes for which test(box) holds"""
    out = np.zeros(len(pts), bool)
    for vol in lp2mapc.all_parts(p_json):
        if not test(vol):
            continue
        (cx, y0, cz), (sx, sy, sz) = vol["pos"], vol.get("size", [1000, 1000, 1000])
        r = math.radians(lp2mapc.volume_yaw(vol))
        c, s = math.cos(r), math.sin(r)
        dx, dz = pts[:, 0] - cx, pts[:, 2] - cz
        lx, lz = dx * c - dz * s, dx * s + dz * c
        out |= (np.abs(lx) <= sx / 2) & (np.abs(lz) <= sz / 2) & (pts[:, 1] >= y0) & (pts[:, 1] <= y0 + sy)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--library")
    a = ap.parse_args()
    folder = os.path.abspath(a.project)
    p = json.load(open(os.path.join(folder, "project.json")))
    print("@progress 0.05 collision", flush=True)
    verts, tris, note = collision(folder, a.library)
    print(f"movement collision: {len(tris)} triangles ({note})")
    print("@progress 0.2 walkable surface", flush=True)
    v, poly = lp2navgen.generate(verts, tris)
    if not len(poly):
        raise SystemExit("no walkable surface found in the movement collision")
    print("@progress 0.6 playable area", flush=True)
    cen = v[poly].mean(1)
    keep = np.zeros(len(poly), bool)
    pts = markers(folder, p)
    reg = regions(v, poly, verts, tris)
    seeds = seed_polys(v, poly, pts)
    if seeds:
        keep = np.isin(reg, reg[seeds])
    else:
        print("no markers on the navmesh: nothing to limit it by, all of it kept")
        keep[:] = True
    kill = (p.get("environment") or {}).get("kill_floor")
    if kill is not None:
        keep &= cen[:, 1] > float(kill)
    keep &= ~in_volumes(p, cen, lp2mapc.volume_kill)
    if any(v.get("limits") for v in p.get("volumes", [])):   # map limits: only what's inside one
        keep &= in_volumes(p, cen, lambda v: bool(v.get("limits")))
    print(f"playable area: {int(keep.sum())} of {len(poly)} polygons ({len(set(reg[seeds].tolist()))} regions from "
          f"{len(seeds)} of {len(pts)} markers)")
    prev = os.path.join(folder, ".preview")
    os.makedirs(prev, exist_ok=True)
    with open(os.path.join(prev, "navmesh.bin"), "wb") as f:
        f.write(struct.pack("<I", len(poly)))
        f.write(v[poly].astype("<f4").tobytes())
        f.write(keep.astype(np.uint8).tobytes())
    kp = poly[keep]
    used = np.unique(kp)
    remap = np.full(len(v), -1)
    remap[used] = np.arange(len(used))
    print("@progress 0.75 waypoints", flush=True)
    tag = (p.get("info") or {}).get("tag") or "custom"
    lnv = lp2navgen.write(os.path.join(folder, "assets", "nav"), tag, v[used], remap[kp], verts, tris)
    rel = lambda f: os.path.relpath(f, folder).replace(os.sep, "/")
    res = dict(lnv=rel(lnv), way=rel(os.path.join(os.path.dirname(lnv), "Way_%s.rAIWayPoint" % tag)),
               polygons=int(keep.sum()), dropped=int((~keep).sum()))
    json.dump(res, open(os.path.join(prev, "navmesh.json"), "w"))
    print("@result " + json.dumps(res))


if __name__ == "__main__":
    sys.exit(main())
