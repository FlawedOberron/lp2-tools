#!/usr/bin/env python3
"""LP2 bot navigation from a map's movement collision: navmesh (rAINavigationMeshList) + waypoints (rAIWayPoint).

  lp2navgen.py build OUTDIR NAME ATARI.rCollision [MORE.rCollision ...]
        OUTDIR/List_NAME.rAINavigationMeshList, OUTDIR/Way_NAME.rAIWayPoint (internal path tool\\AI\\NaviMesh\\NAME\\...)
  lp2navgen.py compare OURS.rAINavigationMeshList STOCK.rAINavigationMeshList
        how much of each mesh's floor the other covers

Movement collision = the map's atari plus any placed pieces' (stock bot areas: ONLINE_12's block arena is
atarionline12 + ataricubescr0 from aArea_TUTOREAL_51_v). Walkable surface: Recast (navgen/navgen, built by navgen/build.sh) over the movement collision, polygons capped at
3 vertices so each is one LNV triangle. The file layout copies the stock training meshes (lp2nav.py docstring):
  - polys: flags 0, links across shared edges, cost = distance between the triangles' centroids
  - areas: a root + a grid of ~40 m leaf boxes (overlapping 5 m in x, 1 m in z like stock), polys sorted by leaf,
    neighbours = the 8 around; area_tail = (leaves, neighbour entries); counts = (links, polys, 3 x polys)
  - quadtree depth 7: 64 x 64 leaves over the bounds (+-1 cm in x / z, +-10 m in y), Morton order (x in the even
    bits), each triangle in every leaf its x / z box touches
Waypoints: a 3 m grid on the navmesh (WAY v16, type 0), one point per floor height, with a 16-direction mask (see
way_mask); quadtree depth 5 (16 x 16 leaves, Morton like the LNV's) over the points' bounds +-50 cm, head (0, n).
"""
import math
import os
import struct
import subprocess
import sys
import tempfile

import numpy as np

import lp2nav
import sbc

HERE = os.path.dirname(os.path.abspath(__file__))
NAVGEN = os.path.join(HERE, "navgen", "navgen.exe" if os.name == "nt" else "navgen")
# Recast settings (cm): cell, cell height, agent height, radius, step, slope (degrees)
# radius: the navmesh keeps this far (cm) from walls and edges, so strips narrower than twice it (wall tops, railings)
# go. Stock training meshes use 0; 40 for ours (user, 2026-11-03: no thin strips, not pushed into walls)
AGENT = dict(cs=20.0, ch=5.0, height=180.0, radius=40.0, climb=55.0, slope=50.0)
LEAF = 4000.0        # area leaf box size (cm)
WAY_STEP = 300.0     # waypoint grid (cm)
SNAP_REACH = 300.0   # snap_corners: a corner moves to a surface at most this far from its triangle's middle height


def collision_mesh(path):
    """a rCollision's triangles: verts (n, 3), tris (m, 3) wound so (v1 - v0) x (v2 - v0) is the stored normal"""
    col = sbc.read(open(path, "rb").read())
    verts = np.array(col["verts"], dtype=np.float32)
    tris, normals = [], []
    for g in col["groups"]:
        for t in col["tris"][g["tri"]:g["tri_end"]]:
            tris.append([g["vert"] + t[3], g["vert"] + t[4], g["vert"] + t[5]])
            normals.append(t[:3])
    tris = np.array(tris, dtype=np.int32)
    normals = np.array(normals, dtype=np.float32)
    v0, v1, v2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    flip = np.einsum("ij,ij->i", cross, normals) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return verts, tris


def recast(verts, tris, agent=AGENT, detail=True):
    """Recast with Recast's own winding: it counts a triangle walkable when (v1 - v0) x (v2 - v0) points up... in its
    left-handed sense, so the triangles go in reversed when floors come out unwalkable (checked by the caller).
    detail: Recast's detail triangles (on the surface across slopes and folds) instead of its polygons, whose
    straight edges cut through a slope's fold or float over it"""
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.bin"), os.path.join(d, "out.bin")
        with open(src, "wb") as f:
            f.write(struct.pack("<II", len(verts), len(tris)))
            f.write(verts.astype("<f4").tobytes())
            f.write(tris.astype("<i4").tobytes())
        a = agent
        r = subprocess.run([NAVGEN, src, dst] + [str(a[k]) for k in ("cs", "ch", "height", "radius", "climb", "slope")]
                           + (["detail"] if detail else []),
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError("navgen failed: " + r.stderr)
        b = open(dst, "rb").read()
    nv, npoly = struct.unpack_from("<II", b)
    o = 8
    v = np.frombuffer(b, "<f4", nv * 3, o).reshape(-1, 3).copy()
    o += nv * 12
    polys = np.frombuffer(b, "<i4", npoly * 3, o).reshape(-1, 3).copy()
    o += npoly * 12
    neis = np.frombuffer(b, "<i4", npoly * 3, o).reshape(-1, 3).copy()
    return v, polys, neis, r.stderr.strip()


def morton(x, z):
    r = 0
    for i in range(8):
        r |= ((x >> i) & 1) << (2 * i) | ((z >> i) & 1) << (2 * i + 1)
    return r


def build_lnv(verts, polys, name):
    """the LNV mesh dict (lp2nav.write_lnv) for triangles polys over verts"""
    cent = verts[polys].mean(axis=1)
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    # leaf areas: a grid of ~LEAF boxes over x / z, polys by centroid
    nx = max(1, math.ceil((hi[0] - lo[0]) / LEAF))
    nz = max(1, math.ceil((hi[2] - lo[2]) / LEAF))
    sx, sz = (hi[0] - lo[0]) / nx, (hi[2] - lo[2]) / nz
    gx = np.clip(((cent[:, 0] - lo[0]) // sx).astype(int), 0, nx - 1)
    gz = np.clip(((cent[:, 2] - lo[2]) // sz).astype(int), 0, nz - 1)
    leaf = gz * nx + gx
    order = np.argsort(leaf, kind="stable")
    polys, cent, leaf = polys[order], cent[order], leaf[order]
    # links across shared edges (both directions), cost = centroid distance
    edges = {}
    for i, t in enumerate(polys):
        for e in range(3):
            a, b = int(t[e]), int(t[(e + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append((i, e))
    P = []
    nlinks = 0
    for i, t in enumerate(polys):
        links = []
        for e in range(3):
            a, b = int(t[e]), int(t[(e + 1) % 3])
            for j, _ in edges[(min(a, b), max(a, b))]:
                if j != i:
                    links.append((j, 0, e, float(np.linalg.norm(cent[i] - cent[j]))))
        nlinks += len(links)
        P.append({"id": i, "flags": [0], "b": 0, "v": (0.0, 0.0, 1.0), "f": 0.0, "extra": [], "tri": [int(x) for x in t],
                  "links": links})
    # areas
    y0, y1 = float(lo[1]) - 500.0, float(hi[1]) + 500.0
    areas = [{"id": 0, "name": "root", "a": 0, "shapes": [(0, (-2500.0, 0.0, -1500.0, 2500.0, 500.0, 0.0))],
              "first": 0, "end": len(P), "parent": 0xFFFF, "children": [], "neighbours": []}]
    used = sorted(set(int(x) for x in leaf))
    index = {c: k + 1 for k, c in enumerate(used)}
    for c in used:
        cx, cz = c % nx, c // nx
        ids = np.nonzero(leaf == c)[0]
        box = (float(lo[0] + cx * sx - 250), y0, float(lo[2] + cz * sz - 50),
               float(lo[0] + (cx + 1) * sx + 250), y1, float(lo[2] + (cz + 1) * sz + 50))
        nb = [index[(cz + dz) * nx + cx + dx] for dz in (-1, 0, 1) for dx in (-1, 0, 1)
              if (dx or dz) and 0 <= cx + dx < nx and 0 <= cz + dz < nz and (cz + dz) * nx + cx + dx in index]
        areas.append({"id": index[c], "name": "area_aabb", "a": 0, "shapes": [(0, box)], "first": int(ids[0]),
                      "end": int(ids[-1]) + 1, "parent": 0, "children": [], "neighbours": sorted(nb)})
    areas[0]["children"] = [a["id"] for a in areas[1:]]
    if len(areas) > 255 or len(P) > 0xFFFF:
        raise ValueError("map too big for the LNV area table (%d leaves, %d polys)" % (len(areas) - 1, len(P)))
    # quadtree
    depth = 7
    n = 1 << (depth - 1)
    box = (float(lo[0]) - 1, float(lo[1]) - 1000, float(lo[2]) - 1, 0.0, float(hi[0]) + 1, float(hi[1]) + 1000, float(hi[2]) + 1, 0.0)
    cx, cz = (box[4] - box[0]) / n, (box[6] - box[2]) / n
    cells = [[] for _ in range(sum(4 ** d for d in range(depth)))]
    off = sum(4 ** d for d in range(depth - 1))
    for i, t in enumerate(polys):
        xs, zs = verts[t, 0], verts[t, 2]
        for x in range(int((xs.min() - box[0]) // cx), int((xs.max() - box[0]) // cx) + 1):
            for z in range(int((zs.min() - box[2]) // cz), int((zs.max() - box[2]) // cz) + 1):
                cells[off + morton(min(x, n - 1), min(z, n - 1))].append((i, 0))
    path = "tool\\AI\\NaviMesh\\%s\\Navi_%s" % (name, name)
    return [{"path": path, "name": "new Navigation", "head": (0, 0, 255), "head_bytes": b"", "points": [],
             "mesh_name": "new Navigation", "verts": [tuple(float(c) for c in v) for v in verts], "polys": P,
             "areas": areas, "area_tail": (len(areas) - 1, sum(len(a["neighbours"]) for a in areas)),
             "counts": (nlinks, len(P), 3 * len(P)), "extra": [],
             "tree": {"depth": depth, "box": list(box), "cells": cells}}]


def surface_points(verts, polys, xz):
    """the navmesh heights under each (x, z): a list per point of y values (one per triangle covering it)"""
    a, b, c = verts[polys[:, 0]], verts[polys[:, 1]], verts[polys[:, 2]]
    out = []
    for x, z in xz:
        d = (b[:, 2] - c[:, 2]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 2] - c[:, 2])
        ok = np.abs(d) > 1e-6
        l1 = np.where(ok, ((b[:, 2] - c[:, 2]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (z - c[:, 2])) / np.where(ok, d, 1), -1)
        l2 = np.where(ok, ((c[:, 2] - a[:, 2]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (z - c[:, 2])) / np.where(ok, d, 1), -1)
        l3 = 1 - l1 - l2
        inside = ok & (l1 >= -1e-4) & (l2 >= -1e-4) & (l3 >= -1e-4)
        ys = (l1 * a[:, 1] + l2 * b[:, 1] + l3 * c[:, 1])[inside]
        out.append(sorted(set(round(float(y), 1) for y in ys)))
    return out


def coverage(va, pa, vb, pb, step=100.0):
    """the share of mesh a's floor (sampled every step cm) that mesh b has within 50 cm of height"""
    lo, hi = va.min(axis=0), va.max(axis=0)
    xs = np.arange(lo[0], hi[0], step)
    zs = np.arange(lo[2], hi[2], step)
    pts = [(x, z) for x in xs for z in zs]
    ya = surface_points(va, pa, pts)
    yb = surface_points(vb, pb, pts)
    total = hit = 0
    for A, B in zip(ya, yb):
        for y in A:
            total += 1
            hit += any(abs(y - q) < 50 for q in B)
    return hit / max(total, 1), total


def load_mesh(path):
    _, ms, _ = lp2nav.load(path)
    m = ms[0]
    return np.array(m["verts"], dtype=np.float32), np.array([p["tri"] for p in m["polys"]], dtype=np.int64)


def inside_solid(verts, tris, points):
    """True per point when the first collision surface straight above it faces up: the point is inside a piece whose
    underside isn't modelled (ONLINE_12's hollow blocks), not under a roof or bridge (those face down)"""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    d = (b[:, 2] - c[:, 2]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 2] - c[:, 2])
    ok = np.abs(d) > 1e-6
    d = np.where(ok, d, 1)
    out = np.zeros(len(points), bool)
    for i, (x, y, z) in enumerate(points):
        l1 = ((b[:, 2] - c[:, 2]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (z - c[:, 2])) / d
        l2 = ((c[:, 2] - a[:, 2]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (z - c[:, 2])) / d
        l3 = 1 - l1 - l2
        h = l1 * a[:, 1] + l2 * b[:, 1] + l3 * c[:, 1]
        hit = ok & (l1 >= 0) & (l2 >= 0) & (l3 >= 0) & (h > y + 10)
        if hit.any():
            j = np.flatnonzero(hit)[np.argmin(h[hit])]
            out[i] = n[j, 1] > 0
    return out


def ray_hits(A, E1, E2, o, d, length):
    """does the ray o + t d (0 < t < length) hit any of the triangles (A, A + E1, A + E2)"""
    p = np.cross(d, E2)
    det = np.einsum("ij,ij->i", E1, p)
    ok = np.abs(det) > 1e-9
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    s = o - A
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, E1)
    v = (q @ d) * inv
    t = np.einsum("ij,ij->i", E2, q) * inv
    return bool((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0) & (t < length)).any())


def way_mask(A, E1, E2, pos):
    """bit b set = open: no collision within 3 m at 1 m up towards 90 - 22.5 b degrees from +x (bit 0 +z, bit 4 +x),
    both u16 halves the same. Fitted to the stock Train_26 points (87% of bits agree, 77% would by all-open; the
    stock halves differ on 4% of points): the real test is how the game's AI uses it"""
    o = np.array(pos, np.float64) + [0, 100, 0]
    m = 0
    for b in range(16):
        a = math.radians(90 - 22.5 * b)
        if not ray_hits(A, E1, E2, o, np.array([math.cos(a), 0, math.sin(a)]), WAY_STEP):
            m |= 1 << b
    return m | m << 16


def build_way(verts, tris, nv, npolys):
    """waypoints on navmesh (nv, npolys) with masks from the collision (verts, tris)"""
    lo, hi = nv.min(axis=0), nv.max(axis=0)
    xs = np.arange(math.ceil(lo[0] / WAY_STEP), math.floor(hi[0] / WAY_STEP) + 1) * WAY_STEP
    zs = np.arange(math.ceil(lo[2] / WAY_STEP), math.floor(hi[2] / WAY_STEP) + 1) * WAY_STEP
    xz = [(float(x), float(z)) for x in xs for z in zs]
    V = verts.astype(np.float64)
    A, E1, E2 = V[tris[:, 0]], V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]]
    points = []
    for (x, z), ys in zip(xz, surface_points(nv, npolys, xz)):
        for y in ys:
            pos = (x, y, z)
            points.append({"id": len(points), "pos": pos, "a": [way_mask(A, E1, E2, pos)], "b": [], "c": [],
                           "type": 0, "data": b""})
    pos = np.array([p["pos"] for p in points])
    mx, mn = pos.max(axis=0) + 50, pos.min(axis=0) - 50
    cells = [[] for _ in range(341)]
    for i, p in enumerate(pos):
        f = (p - mn) / (mx - mn)
        cells[85 + morton(min(int(f[0] * 16), 15), min(int(f[2] * 16), 15))].append((i, 0))
    return {"points": points, "head": (0, len(points)),
            "tree": {"depth": 5, "box": [float(c) for c in list(mx) + list(mn)], "cells": cells}}


def snap_corners(verts, tris, v, p):
    """each triangle's corners onto the collision surface nearest the triangle's middle height, then corners at the
    same place joined again -> v, p. Recast gives a corner the height of the highest walkable span around it, so a
    floor corner at the foot of a ledge sits on the ledge's top: spikes and wedges up the wall, jagged floor edges"""
    surf = surface_points(verts, tris, [(x, z) for x, _, z in v])
    T = v[p].copy()
    for t in range(len(p)):
        ref = float(np.median(T[t, :, 1]))
        for k in range(3):
            ys = surf[p[t, k]]
            if ys:
                y = min(ys, key=lambda q: abs(q - ref))
                if abs(y - ref) < SNAP_REACH:
                    T[t, k, 1] = y
    flat = T.reshape(-1, 3)
    key = np.round(flat * [10, 2, 10]).astype(np.int64)   # 1 mm across, 5 mm up
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    p = inv.reshape(-1, 3)
    ok = (p[:, 0] != p[:, 1]) & (p[:, 1] != p[:, 2]) & (p[:, 0] != p[:, 2])
    return flat[first], p[ok]


def generate(verts, tris, log=print):
    """the walkable surface of a collision mesh (cm): Recast, minus polygons inside solid pieces, heights snapped
    onto the collision -> v (n, 3), p (m, 3) triangles"""
    v, p, _, rlog = recast(verts, tris)
    if len(p) == 0:   # wound the other way for Recast
        v, p, _, rlog = recast(verts, tris[:, [0, 2, 1]])
    log("recast: " + rlog)
    v, p = snap_corners(verts, tris, v, p)
    # inside a solid piece: the centre and at least 2 corners (on the surface after snapping). The centre alone
    # misreads big polygons over sloped or stepped roofs, whose middle lies under the roof's own surface
    vin = inside_solid(verts, tris, v)
    keep = ~(inside_solid(verts, tris, v[p].mean(axis=1)) & (vin[p].sum(axis=1) >= 2))
    p = p[keep]
    used = np.unique(p)
    remap = np.full(len(v), -1)
    remap[used] = np.arange(len(used))
    v, p = v[used], remap[p]
    log("dropped %d polygons inside solid pieces" % (~keep).sum())
    return v, p.astype(np.int64)


def write(outdir, name, v, p, verts, tris, log=print):
    """List_NAME.rAINavigationMeshList + Way_NAME.rAIWayPoint in outdir (waypoints checked against the collision
    verts / tris) -> the LNV's path"""
    meshes = build_lnv(v, p, name)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "List_%s.rAINavigationMeshList" % name)
    open(out, "wb").write(lp2nav.write_lnv(meshes))
    way = build_way(verts, tris, v, p)
    wout = os.path.join(outdir, "Way_%s.rAIWayPoint" % name)
    open(wout, "wb").write(lp2nav.write_way(way))
    log("%s: %d points, %d with a blocked direction" % (wout, len(way["points"]),
                                                       sum(q["a"][0] != 0xFFFFFFFF for q in way["points"])))
    m = meshes[0]
    log("%s: %d verts, %d polys, %d links, %d leaf areas" % (out, len(m["verts"]), len(m["polys"]), m["counts"][0],
                                                            m["area_tail"][0]))
    return out


def build(outdir, name, cols):
    parts = [collision_mesh(c) for c in cols]
    verts = np.concatenate([v for v, _ in parts])
    base = np.cumsum([0] + [len(v) for v, _ in parts[:-1]])
    tris = np.concatenate([t + b for (_, t), b in zip(parts, base)])
    v, p = generate(verts, tris)
    return write(outdir, name, v, p, verts, tris)


def main(argv):
    if len(argv) >= 5 and argv[1] == "build":
        build(argv[2], argv[3], argv[4:])
    elif len(argv) == 4 and argv[1] == "compare":
        va, pa = load_mesh(argv[2])
        vb, pb = load_mesh(argv[3])
        ab, n = coverage(va, pa, vb, pb)
        ba, m = coverage(vb, pb, va, pa)
        print("ours covered by stock: %.1f%% of %d samples; stock covered by ours: %.1f%% of %d" % (ab * 100, n, ba * 100, m))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
