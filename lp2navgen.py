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


def _leaves(verts, polys):
    """leaf areas: a grid of ~LEAF boxes over x / z, polys by centroid -> leaf per poly, nx, nz, sx, sz, lo, hi"""
    cent = verts[polys].mean(axis=1)
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    nx = max(1, math.ceil((hi[0] - lo[0]) / LEAF))
    nz = max(1, math.ceil((hi[2] - lo[2]) / LEAF))
    sx, sz = (hi[0] - lo[0]) / nx, (hi[2] - lo[2]) / nz
    gx = np.clip(((cent[:, 0] - lo[0]) // sx).astype(int), 0, nx - 1)
    gz = np.clip(((cent[:, 2] - lo[2]) // sz).astype(int), 0, nz - 1)
    return gz * nx + gx, nx, nz, sx, sz, lo, hi


def lnv_order(verts, polys):
    """build_lnv's polygon order: LNV polygon k is polys[order[k]]"""
    return np.argsort(_leaves(verts, polys)[0], kind="stable")


def build_lnv(verts, polys, name):
    """the LNV mesh dict (lp2nav.write_lnv) for triangles polys over verts"""
    cent = verts[polys].mean(axis=1)
    leaf, nx, nz, sx, sz, lo, hi = _leaves(verts, polys)
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


SNAP_JOIN = 1.5      # snap_corners: copies of one Recast corner snapped within this x the step height (climb) of each
                     # other stay one vertex (Guardian's stairs: copies 40 - 70 cm apart on 55 cm steps; ledges 90+)


def snap_corners(verts, tris, v, p, join=SNAP_JOIN * AGENT["climb"]):
    """each triangle's corners onto the collision surface nearest the triangle's middle height -> v, p. Recast gives a
    corner the height of the highest walkable span around it, so a floor corner at the foot of a ledge sits on the
    ledge's top: spikes and wedges up the wall, jagged floor edges. A corner's copies (one per triangle using it) that
    land within `join` of each other in height are one vertex again (their median height): only a corner really on two
    levels (a ledge top and the floor under it) splits. (Until 2026-11-13 copies were joined only when they landed on
    the same spot to 5 mm, which cut ramps and stairs into dozens of pieces bots couldn't path across.)"""
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
    # per Recast corner: its copies' heights, grouped where they lie within `join` of the next
    uses = {}
    for t in range(len(p)):
        for k in range(3):
            uses.setdefault(int(p[t, k]), []).append((float(T[t, k, 1]), t, k))
    out_v, newp = [], np.empty_like(p)
    for o, lst in uses.items():
        lst.sort()
        group = [lst[0]]
        for item in lst[1:] + [None]:
            if item is not None and item[0] - group[-1][0] <= join:
                group.append(item)
                continue
            y = float(np.median([g[0] for g in group]))
            idx = len(out_v)
            out_v.append((float(v[o, 0]), y, float(v[o, 2])))
            for _, t, k in group:
                newp[t, k] = idx
            if item is not None:
                group = [item]
    nv = np.array(out_v, dtype=np.float32).reshape(-1, 3)
    ok = (newp[:, 0] != newp[:, 1]) & (newp[:, 1] != newp[:, 2]) & (newp[:, 0] != newp[:, 2])
    return nv, newp[ok]


def generate(verts, tris, log=print, agent=None):
    """the walkable surface of a collision mesh (cm): Recast, minus polygons inside solid pieces, heights snapped
    onto the collision -> v (n, 3), p (m, 3) triangles. agent: Recast settings over AGENT (climb, slope, radius)"""
    agent = dict(AGENT, **(agent or {}))
    v, p, _, rlog = recast(verts, tris, agent)
    if len(p) == 0:   # wound the other way for Recast
        v, p, _, rlog = recast(verts, tris[:, [0, 2, 1]], agent)
    log("recast: " + rlog)
    v, p = snap_corners(verts, tris, v, p, join=SNAP_JOIN * agent["climb"])
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


# ---------------------------------------------------------------- pieces and welds
# A piece: polygons joined across shared edges. Recast splits a floor into pieces where a step is higher than the climb,
# a slope steeper than the slope limit, or a ramp narrower than twice the radius; bots' paths (the game's search over
# the navmesh links) can't cross between pieces. A weld joins two pieces: links both ways between a polygon on each
# side, across the open edges facing each other (the game plans over such links: Capcom's Train_46 has some).
# A weld: (poly a, its edge, poly b, its edge, a's edge middle, b's edge middle, manual) in the full polygon list.
WELD_COST = 50.0     # added to a weld's centre distance: an edge-shared way round of the same length wins
WELD_CELL = 200.0    # grid for the edge search (cm)
WELD_FIND = 300.0    # a manual weld's end: the polygon under it, else the nearest centre within this


def _edges(p):
    """{(va, vb) sorted: [(poly, edge index)]}"""
    edges = {}
    for i, t in enumerate(p):
        for e in range(3):
            a, b = int(t[e]), int(t[(e + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append((i, e))
    return edges


def pieces(p, welds=(), keep=None):
    """piece number per polygon (0 the largest), over shared edges and welds; keep: only those polygons (the rest
    -1) -> int array"""
    n = len(p)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    ok = np.ones(n, bool) if keep is None else np.asarray(keep, bool)
    for ps in _edges(p).values():
        for (j, _) in ps[1:]:
            if ok[ps[0][0]] and ok[j]:
                parent[find(j)] = find(ps[0][0])
    for w in welds:
        if ok[w[0]] and ok[w[2]]:
            parent[find(w[2])] = find(w[0])
    root = np.array([find(i) for i in range(n)])
    out = np.full(n, -1)
    roots, counts = np.unique(root[ok], return_counts=True)
    for k, r in enumerate(roots[np.argsort(-counts, kind="stable")]):
        out[root == r] = k
    out[~ok] = -1
    return out


def _seg_gap(a0, a1, b0, b1):
    """closest points of two segments seen from above (x / z) -> (flat distance, height difference there, the two
    points)"""
    p, q = a0[[0, 2]], b0[[0, 2]]
    d1, d2, r = a1[[0, 2]] - p, b1[[0, 2]] - q, p - q
    aa, ee, ff = d1 @ d1, d2 @ d2, d2 @ r
    if aa < 1e-9 and ee < 1e-9:
        s = t = 0.0
    elif aa < 1e-9:
        s, t = 0.0, min(max(ff / ee, 0.0), 1.0)
    else:
        c = d1 @ r
        if ee < 1e-9:
            t, s = 0.0, min(max(-c / aa, 0.0), 1.0)
        else:
            bb = d1 @ d2
            den = aa * ee - bb * bb
            s = min(max((bb * ff - c * ee) / den, 0.0), 1.0) if den > 1e-9 else 0.0
            t = (bb * s + ff) / ee
            if t < 0.0:
                t, s = 0.0, min(max(-c / aa, 0.0), 1.0)
            elif t > 1.0:
                t, s = 1.0, min(max((bb - c) / aa, 0.0), 1.0)
    pa, pb = a0 + (a1 - a0) * s, b0 + (b1 - b0) * t
    return float(np.hypot(pa[0] - pb[0], pa[2] - pb[2])), float(abs(pa[1] - pb[1])), pa, pb


WELD_SIGHT = 60.0    # cm above both ends: an automatic weld needs a clear line through the collision there (no wall)


def auto_welds(v, p, gap, up, log=print, verts=None, tris=None):
    """welds between open edges of different pieces at most gap (cm) apart across and up (cm) apart in height, with a
    clear line WELD_SIGHT above them through the collision verts / tris (when given)"""
    if gap <= 0 or not len(p):
        return []
    edges = _edges(p)
    piece = pieces(p)
    opens = [(ps[0][0], ps[0][1], a, b) for (a, b), ps in edges.items() if len(ps) == 1]
    grid = {}
    V = v.astype(np.float64)
    for k, (i, e, a, b) in enumerate(opens):
        lo = np.minimum(V[a], V[b]) - gap
        hi = np.maximum(V[a], V[b]) + gap
        for cx in range(int(lo[0] // WELD_CELL), int(hi[0] // WELD_CELL) + 1):
            for cz in range(int(lo[2] // WELD_CELL), int(hi[2] // WELD_CELL) + 1):
                grid.setdefault((cx, cz), []).append(k)
    if verts is not None:
        C = verts.astype(np.float64)
        A, E1, E2 = C[tris[:, 0]], C[tris[:, 1]] - C[tris[:, 0]], C[tris[:, 2]] - C[tris[:, 0]]
    blocked = 0
    seen, out = set(), []
    for ks in grid.values():
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                ka, kb = ks[x], ks[y]
                i, ei, a0, a1 = opens[ka]
                j, ej, b0, b1 = opens[kb]
                if piece[i] == piece[j] or (min(ka, kb), max(ka, kb)) in seen:
                    continue
                seen.add((min(ka, kb), max(ka, kb)))
                flat, dy, pa, pb = _seg_gap(V[a0], V[a1], V[b0], V[b1])
                if flat > gap or dy > up:
                    continue
                if verts is not None:
                    o, d = pa + [0, WELD_SIGHT, 0], pb - pa
                    dist = float(np.linalg.norm(d))
                    if dist > 1.0 and ray_hits(A, E1, E2, o, d / dist, dist):
                        blocked += 1
                        continue
                out.append((i, ei, j, ej, (V[a0] + V[a1]) / 2, (V[b0] + V[b1]) / 2, False))
    # one weld per polygon pair
    uniq = {}
    for w in out:
        uniq.setdefault((min(w[0], w[2]), max(w[0], w[2])), w)
    out = list(uniq.values())
    before, after = len(set(piece.tolist())), len(set(pieces(p, out).tolist()))
    log("welds: %d automatic (gaps up to %.0f cm across, %.0f cm up; %d more blocked by walls): %d pieces -> %d"
        % (len(out), gap, up, blocked, before, after))
    return out


def poly_at(v, p, q, reach=WELD_FIND):
    """the polygon under q (x / z inside, the nearest in height within 250 cm), else the nearest centre within reach;
    -1 none"""
    q = np.asarray(q, float)
    A, B, C = v[p[:, 0]], v[p[:, 1]], v[p[:, 2]]
    d = (B[:, 2] - C[:, 2]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 2] - C[:, 2])
    d = np.where(np.abs(d) < 1e-9, 1e-9, d)
    l1 = ((B[:, 2] - C[:, 2]) * (q[0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (q[2] - C[:, 2])) / d
    l2 = ((C[:, 2] - A[:, 2]) * (q[0] - C[:, 0]) + (A[:, 0] - C[:, 0]) * (q[2] - C[:, 2])) / d
    l3 = 1 - l1 - l2
    h = l1 * A[:, 1] + l2 * B[:, 1] + l3 * C[:, 1]
    inside = (l1 >= -0.01) & (l2 >= -0.01) & (l3 >= -0.01) & (np.abs(h - q[1]) < 250)
    if inside.any():
        c = np.flatnonzero(inside)
        return int(c[np.argmin(np.abs(h[c] - q[1]))])
    cen = v[p].mean(1)
    dist = np.linalg.norm(cen - q, axis=1)
    i = int(dist.argmin())
    return i if dist[i] < reach else -1


def manual_welds(v, p, pairs, log=print):
    """project.json "nav_welds" [{a: [x, y, z], b: [x, y, z]}] (cm) -> welds between the polygons at the two ends,
    across each one's edge facing the other end"""
    out = []
    V = v.astype(np.float64)
    for w in pairs:
        try:
            a, b = np.asarray(w["a"], float), np.asarray(w["b"], float)
        except (KeyError, TypeError, ValueError):
            continue
        i, j = poly_at(V, p, a), poly_at(V, p, b)
        if i < 0 or j < 0 or i == j:
            log("weld from %s to %s: %s" % (np.round(a).tolist(), np.round(b).tolist(), "an end is off the navmesh" if min(i, j) < 0 else "both ends on one polygon"))
            continue

        def facing(k, to):
            t = p[k]
            mids = [(V[t[e]] + V[t[(e + 1) % 3]]) / 2 for e in range(3)]
            e = int(np.argmin([np.hypot(*(m - to)[[0, 2]]) for m in mids]))
            return e, mids[e]
        ei, ma = facing(i, b)
        ej, mb = facing(j, a)
        out.append((i, ei, j, ej, ma, mb, True))
    if pairs:
        log("welds: %d of %d placed" % (len(out), len(pairs)))
    return out


def weld_links(m, welds, order_inv, log=print):
    """welds (kept polygon numbers, before build_lnv's sort) as LNV links both ways; order_inv: kept number -> LNV
    polygon. m: the LNV mesh dict, changed in place -> links added"""
    V = np.asarray(m["verts"], float)
    T = np.array([q["tri"] for q in m["polys"]])
    cent = V[T].mean(axis=1) if len(T) else np.zeros((0, 3))
    added = 0
    for (i, ei, j, ej, *_rest) in welds:
        a, b = int(order_inv[i]), int(order_inv[j])
        cost = float(np.linalg.norm(cent[a] - cent[b])) + WELD_COST
        for x, e, y in ((a, ei, b), (b, ej, a)):
            P = m["polys"][x]
            if not any(l[0] == y for l in P["links"]):
                P["links"].append((y, 0, e, cost))
                added += 1
    if added:
        c = list(m["counts"])
        c[0] += added
        m["counts"] = tuple(c)
    log("navmesh: %d weld links" % added)
    return added


CROSS_KINDS = ("drop", "jump")
CROSS_REACH = 300.0   # cm from a link's end to the polygon it's put on


def cross_links(m, links, log=print):
    """Drop and jump links (navzones.json "links": kind, a, b) as navmesh links between the polygons at their two ends,
    which share no edge: the game's own pathing then plans over ledges and gaps (Capcom's training navmesh Train_46 has
    14 such links, 2 - 4 m up or down, costs in the thousands against ~100 for a step across an edge). The crossing edge
    is the one of the start polygon facing the far end. Costed high, so walking round stays the choice where there is a
    way round. m: an LNV mesh dict (build_lnv / lp2nav.load), changed in place -> links added."""
    V = np.asarray(m["verts"], float)
    if not len(V):
        return 0
    T = np.array([p["tri"] for p in m["polys"]])
    cent = V[T].mean(axis=1)

    def poly_at(q):
        q = np.asarray(q, float)
        d = np.linalg.norm(cent - q, axis=1)
        i = int(d.argmin())
        return i if d[i] < CROSS_REACH else -1
    added, seen = 0, set()
    for e in links:
        if e.get("kind") not in CROSS_KINDS:
            continue
        i, j = poly_at(e["a"]), poly_at(e["b"])
        if i < 0 or j < 0 or i == j or (i, j) in seen:
            continue
        P = m["polys"][i]
        if any(l[0] == j for l in P["links"]):
            continue
        seen.add((i, j))
        b = np.asarray(e["b"], float)
        mids = [(V[P["tri"][k]] + V[P["tri"][(k + 1) % 3]]) / 2 for k in range(3)]
        edge = int(np.argmin([np.linalg.norm((mid - b)[[0, 2]]) for mid in mids]))
        dist = float(np.linalg.norm(cent[i] - cent[j]))
        P["links"].append((j, 0, edge, 3.0 * dist + 1500.0))
        added += 1
    if added:
        c = list(m["counts"])
        c[0] += added
        m["counts"] = tuple(c)
    log("navmesh: %d drop / jump links across ledges" % added)
    return added


LADDER_FLAG = 0x8000   # a ladder polygon (Capcom's training navmeshes: vertical quads joining two floors)


def write(outdir, name, v, p, verts, tris, log=print, links=None, welds=None, ladder=None):
    """List_NAME.rAINavigationMeshList + Way_NAME.rAIWayPoint in outdir (waypoints checked against the collision
    verts / tris) -> the LNV's path. links: navzones.json links, drops and jumps become navmesh links (cross_links).
    welds: in p's polygon numbers (auto_welds / manual_welds), links both ways (weld_links)"""
    meshes = build_lnv(v, p, name)
    order = lnv_order(v, p)
    inv = np.empty(len(order), int)
    inv[order] = np.arange(len(order))
    if welds:
        weld_links(meshes[0], welds, inv, log)
    if ladder is not None and np.any(ladder):
        for i in np.flatnonzero(ladder):
            meshes[0]["polys"][inv[i]]["flags"] = [LADDER_FLAG]
        log("navmesh: %d ladder polygons" % int(np.sum(ladder)))
    if links:
        cross_links(meshes[0], links, log)
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
