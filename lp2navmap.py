#!/usr/bin/env python3
"""A project's bot navigation (the editor's Build navmesh): lp2navgen.py over the movement collision as the export
builds it (lp2colview.project_collision), limited to the playable area.

project.json "nav_mesh": a hand-edited navmesh (OBJ, metres, Y up; the editor's Hand edit), used instead of generating
one. "nav_settings": {climb, slope, radius (Recast, cm / degrees), weld (cm: weld pieces whose open edges are
this close, 0 off)}; "nav_welds": [{a, b}] welds placed by hand (cm). Welds: lp2navgen.auto_welds / manual_welds.
"nav_added" / "nav_removed": left-out parts put back and parts taken out by hand (marked()); put back first.

  lp2navmap.py PROJECT_DIR [--library LIB]

Playable area: the walkable regions connected to the layout's markers (spawns, pickups, VS, posts in every set),
through shared edges, short jumps and drops (LEDGE_GAP across, LEDGE_DROP up or down) or the grapple (GRAPPLE from
AIM_UP over an edge to another region's edge, in line of sight) or a weld, above the kill floor, outside kill volumes and, when the project has map limits volumes ("limits"), inside one of them. The rest (roofs, outside ledges, sealed rooms, under the map) is dropped.

Writes PROJECT/assets/nav/List_<tag>.rAINavigationMeshList + Way_<tag>.rAIWayPoint and the editor's view
PROJECT/.preview/navmesh.bin: u32 triangle count, per triangle 3 x (x, y, z) f32 cm, then per triangle u8 (1 kept,
0 dropped: outside the playable area), per triangle u16 piece (0 the largest, 0xffff dropped), u32 welds + per weld
6 f32 + u8 manual; .preview/navmesh.json (and "@result"): the files (project-relative) and counts,
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
LADDER_WIDTH = 80.0     # cm: a ladder's navmesh quad (Capcom's training navmeshes: ~80 cm, flag 0x8000)
LADDER_OUT = (0.0, 40.0, 80.0, 120.0)   # cm out from the ladder's plane (both sides) where its floors are looked for
LADDER_FOOT = 80.0      # cm: the bottom floor's height within this of the ladder's foot
LADDER_TOP = 150.0      # cm: the top floor's within this of the foot + height


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


def _floor_at(v, p, q, tol, n):
    """the walkable polygon (among the first n) whose surface is under / over q in x / z and within tol of q's height
    (the nearest in height); -1 none"""
    q = np.asarray(q, float)
    A, B, C = v[p[:n, 0]], v[p[:n, 1]], v[p[:n, 2]]
    d = (B[:, 2] - C[:, 2]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 2] - C[:, 2])
    flat = np.abs(d) > 1.0   # vertical triangles (ladders) have no x / z area
    d = np.where(flat, d, 1.0)
    l1 = ((B[:, 2] - C[:, 2]) * (q[0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (q[2] - C[:, 2])) / d
    l2 = ((C[:, 2] - A[:, 2]) * (q[0] - C[:, 0]) + (A[:, 0] - C[:, 0]) * (q[2] - C[:, 2])) / d
    l3 = 1 - l1 - l2
    h = l1 * A[:, 1] + l2 * B[:, 1] + l3 * C[:, 1]
    ok = flat & (l1 >= -0.02) & (l2 >= -0.02) & (l3 >= -0.02) & (np.abs(h - q[1]) <= tol)
    if not ok.any():
        return -1
    c = np.flatnonzero(ok)
    return int(c[np.argmin(np.abs(h[c] - q[1]))])


def add_ladders(v, p, ladders, log=print):
    """project.json "ladders" [{pos (the foot, cm), yaw (deg), height (cm)}] (stock: the om8322 objects) -> the
    navmesh with a vertical LADDER_WIDTH quad per ladder (two triangles, appended), each welded to the floor at its foot
    and the one at its top (looked for LADDER_OUT out from its plane, either side). The game's own pathing climbs a
    0x8000 polygon (lp2navgen.write flags them). -> v, p, ladder mask over p, welds (lp2navgen weld tuples), links
    [(bottom poly, top poly, foot, top)] for the zones"""
    n = len(p)
    V = v.astype(np.float64)
    nv, nt, mask, welds, links = [], [], [], [], []
    skipped = 0

    def facing(k, to):
        t = p[k]
        mids = [(V[t[e]] + V[t[(e + 1) % 3]]) / 2 for e in range(3)]
        e = int(np.argmin([np.hypot(*(m - to)[[0, 2]]) for m in mids]))
        return e, mids[e]
    for lad in ladders:
        try:
            foot = np.asarray(lad["pos"], float)
            yaw, height = math.radians(float(lad.get("yaw", 0.0))), float(lad["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if height < 50:
            continue
        across = np.array([math.cos(yaw), 0.0, -math.sin(yaw)])
        normal = np.array([math.sin(yaw), 0.0, math.cos(yaw)])
        top = foot + [0.0, height, 0.0]

        def find(at, tol):
            for off in LADDER_OUT:
                hits = []
                for side in (1.0, -1.0):
                    k = _floor_at(V, p, at + normal * off * side, tol, n)
                    if k >= 0:
                        hits.append(k)
                if hits:
                    return hits[0] if len(hits) == 1 else min(hits, key=lambda k: abs(V[p[k]].mean(0)[1] - at[1]))
            return -1
        lo, hi = find(foot, LADDER_FOOT), find(top, LADDER_TOP)
        if lo < 0 or hi < 0 or lo == hi:
            skipped += 1
            log("ladder at %s (%.0f cm): %s" % (np.round(foot).tolist(), height, "no floor at its foot" if lo < 0 else
                                                  "no floor at its top" if hi < 0 else "foot and top on one polygon"))
            continue
        base = len(V) + len(nv)
        b0, b1 = foot - across * LADDER_WIDTH / 2, foot + across * LADDER_WIDTH / 2
        nv += [b0, b1, b1 + [0, height, 0], b0 + [0, height, 0]]
        t0, t1 = n + len(nt), n + len(nt) + 1
        nt += [[base, base + 1, base + 2], [base, base + 2, base + 3]]   # edge 0 of t0: the bottom; edge 1 of t1: the top
        mask += [True, True]
        eb, mb = facing(lo, foot)
        et, mt = facing(hi, top)
        welds.append((t0, 0, lo, eb, foot.copy(), mb, False))
        welds.append((t1, 1, hi, et, top.copy(), mt, False))
        links.append((lo, hi, foot, top))
    if ladders:
        log("ladders: %d of %d on the navmesh" % (len(links), len(links) + skipped))
    if not nt:
        return v, p, np.zeros(n, bool), [], []
    v2 = np.concatenate([v, np.asarray(nv, v.dtype)])
    p2 = np.concatenate([p, np.asarray(nt, p.dtype)])
    return v2, p2, np.concatenate([np.zeros(n, bool), np.array(mask)]), welds, links


def regions(v, p, verts=None, tris=None, welds=(), skip=None, late=()):
    """polygons joined across shared edges and welds, then regions joined by jumps and the grapple (between open-edge
    vertices; the grapple needs a clear line through the collision verts / tris), then by the late welds (the ladders':
    joined first, they'd merge regions early and those would share one GRAPPLE_TRIES budget, map 08 lost 380 polygons)
    -> region id per polygon"""
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
    for w in welds:
        _union(parent, w[0], w[2])
    open_v = {}
    for (a, b), ps in edges.items():
        if len(ps) == 1 and (skip is None or not skip[ps[0]]):   # a ladder's sides jump nowhere
            open_v.setdefault(a, ps[0])
            open_v.setdefault(b, ps[0])
    def done():
        for w in late:
            _union(parent, w[0], w[2])
        return np.array([_find(parent, i) for i in range(n)])
    if not open_v:
        return done()
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
    return done()


def seed_polys(v, p, pts):
    """per marker: the polygon under it (its x / z inside, the floor SEED_BELOW under to SEED_ABOVE over it), else
    the nearest centroid within 3 m"""
    a, b, c = v[p[:, 0]], v[p[:, 1]], v[p[:, 2]]
    cen = v[p].mean(1)
    d = (b[:, 2] - c[:, 2]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 2] - c[:, 2])
    ok = np.abs(d) > 1.0   # not the vertical ladder quads (or slivers): a marker stands on a floor
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
        dist = np.where(ok, np.linalg.norm(cen - [x, y, z], axis=1), np.inf)
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


ZONE_CELL = 2000.0      # cm: automatic zones are the walkable surface cut on this x / z grid, each floor / ledge its own
ZONE_MIN_AREA = 6e4     # cm2 (6 m2): smaller zones (slivers) join their largest walkable neighbour
JUMP_UP = 120.0         # cm a jump link may climb (higher only drops down)
GRAPPLE_SCAN = 3300.0   # cm: grapple links are looked for up to this (the Anchor Range rule's 3X); each keeps its length
GRAPPLE_MIN_UP = 200.0  # cm: a grapple link must climb at least this (lower: walk / jump)
GRAPPLE_ZONE_TRIES = 12 # line-of-sight tests per pair of zones
LAUNCH_STEP = 1 / 60.0  # s: the launch trajectory's step (force.cpp moves a carried character every frame)
EARTH = 980.0           # cm/s2 (force.cpp kEarth), times the map's gravity


def zone_outline(tri, v):
    """a zone's outer edges (edges of its triangles no other of its triangles shares), chained into loops of points
    (cm, rounded); a loop that doesn't close ends where its edges run out"""
    count = {}
    for t in tri:
        for e in range(3):
            a, b = int(t[e]), int(t[(e + 1) % 3])
            k = (min(a, b), max(a, b))
            count[k] = count.get(k, 0) + 1
    nxt = {}
    for (a, b), c in count.items():
        if c == 1:
            nxt.setdefault(a, []).append(b)
            nxt.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in list(nxt):
        if all((min(start, x), max(start, x)) in seen for x in nxt[start]):
            continue
        loop, cur, prev = [start], start, None
        while True:
            options = [x for x in nxt[cur] if x != prev and (min(cur, x), max(cur, x)) not in seen]
            if not options:
                break
            x = options[0]
            seen.add((min(cur, x), max(cur, x)))
            prev, cur = cur, x
            loop.append(cur)
            if cur == start:
                break
        if len(loop) >= 3:
            pts = [np.asarray(v[i], np.float64) for i in loop]
            keep = [pts[0]]
            for k in range(1, len(pts) - 1):   # drop points on a straight run (under ~3 degrees and 20 cm of rise off it)
                d1, d2 = pts[k] - keep[-1], pts[k + 1] - pts[k]
                n1, n2 = np.linalg.norm(d1), np.linalg.norm(d2)
                if n1 < 1e-3 or n2 < 1e-3 or np.dot(d1, d2) / (n1 * n2) < 0.9986 or abs(d1[1] / n1 - d2[1] / n2) * n2 > 20:
                    keep.append(pts[k])
            keep.append(pts[-1])
            loops.append([[round(float(c), 1) for c in q] for q in keep])
    return loops


def zones_and_links(v, poly, keep, verts, tris, p, grapple_scan=GRAPPLE_SCAN, welds=(), ladders=(), skip=None):
    """The playable navmesh cut into zones (bots route zone to zone) and the links between them, each with how it's
    crossed: walk (shared edge, both ways), jump (a gap or step up to JUMP_UP, both ways), drop (down a ledge, one way),
    grapple (up to a higher lip in sight, one way; "length" so bots skip ones beyond the match's anchor range) and launch
    (an impulse / velocity force volume to where its trajectory lands, one way), ladder (add_ladders: both ways; the
    ladder's own polygons are in no zone). Zones: manual zone volumes ("zone":
    name) first, the rest cut on a ZONE_CELL grid, each walkable patch in a cell its own zone (so floors differ).
    -> {zones: [{name, pos, size}], links: [{from, to, kind, a, b, length?}]}"""
    idx = np.flatnonzero(keep if skip is None else keep & ~skip)
    if not len(idx):
        return {"zones": [], "links": []}
    tri = poly[idx]
    P = v[tri].astype(np.float64)               # n x 3 x 3
    cen = P.mean(1)
    area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    n = len(idx)
    edges = {}
    for i, t in enumerate(tri):
        for e in range(3):
            a, b = int(t[e]), int(t[(e + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append(i)
    nbr = [[] for _ in range(n)]
    for ps in edges.values():
        for x in ps:
            for y in ps:
                if x != y:
                    nbr[x].append(y)
    local = {int(g): k for k, g in enumerate(idx)}   # full polygon number -> kept number
    kwelds = [(local[w[0]], local[w[2]], w[4], w[5]) for w in welds if w[0] in local and w[2] in local]
    for x, y, _, _ in kwelds:   # welded pieces walk into each other
        nbr[x].append(y)
        nbr[y].append(x)
    # manual zones
    zone = np.full(n, -1)
    names = []
    tags = []
    for vol in lp2mapc.all_parts(p):
        nm = vol.get("zone")
        if not nm:
            continue
        inside = in_volumes({"volumes": [vol]}, cen, lambda q: True) & (zone < 0)
        if inside.any():
            zone[inside] = len(names)
            names.append(str(nm))
            tags.append([str(t) for t in vol.get("zone_tags", []) if str(t).strip()])
    # automatic: per grid cell, patches joined by shared edges inside the cell
    cell = [tuple(c) for c in np.floor(cen[:, [0, 2]] / ZONE_CELL).astype(np.int64)]
    for i in range(n):
        if zone[i] >= 0:
            continue
        z = len(names)
        names.append("")
        tags.append([])
        zone[i] = z
        stack = [i]
        while stack:
            j = stack.pop()
            for k in nbr[j]:
                if zone[k] < 0 and cell[k] == cell[i]:
                    zone[k] = z
                    stack.append(k)
    # slivers join their largest walkable neighbour (automatic zones only)
    for _ in range(3):
        zarea = np.bincount(zone, weights=area, minlength=len(names))
        changed = False
        for z in np.flatnonzero(zarea < ZONE_MIN_AREA):
            if names[z]:
                continue
            members = np.flatnonzero(zone == z)
            best, best_a = -1, -1.0
            for j in members:
                for k in nbr[j]:
                    if zone[k] != z and zarea[zone[k]] > best_a:
                        best, best_a = zone[k], zarea[zone[k]]
            if best >= 0:
                zone[members] = best
                changed = True
        if not changed:
            break
    used = sorted(set(zone.tolist()))
    renum = {z: k for k, z in enumerate(used)}
    zone = np.array([renum[z] for z in zone])
    names = [names[z] for z in used]
    tags = [tags[z] for z in used]
    nz = len(used)
    out_zones = []
    for z in range(nz):
        m = np.flatnonzero(zone == z)
        w = area[m] / max(area[m].sum(), 1e-6)
        mean = (cen[m] * w[:, None]).sum(0)
        at = cen[m[np.argmin(np.linalg.norm(cen[m] - mean, axis=1))]]   # a real spot on the mesh near the middle
        lo, hi = P[m].reshape(-1, 3).min(0), P[m].reshape(-1, 3).max(0)
        out_zones.append({"name": names[z] or "z%d" % z, "tags": tags[z], "pos": [round(float(c), 1) for c in at],
                          "size": [round(float(c), 1) for c in hi - lo], "outline": zone_outline(tri[m], v)})
    links = {}

    def link(za, zb, kind, a, b, length=None):
        if za == zb:
            return
        key = (int(za), int(zb), kind)
        d = float(np.linalg.norm(np.asarray(b) - np.asarray(a))) if length is None else length
        if key in links and links[key][0] <= d:
            return
        links[key] = (d, [round(float(c), 1) for c in a], [round(float(c), 1) for c in b])

    # walk: shared edges
    for (va, vb), ps in edges.items():
        zs = {zone[x] for x in ps}
        if len(zs) > 1:
            mid = (v[va] + v[vb]) / 2.0
            for x in zs:
                for y in zs:
                    if x != y:
                        link(x, y, "walk", mid, mid, length=0.0)
    for x, y, ma, mb in kwelds:
        if zone[x] != zone[y]:
            link(zone[x], zone[y], "walk", ma, mb)
            link(zone[y], zone[x], "walk", mb, ma)
    # open-edge points (one triangle on the edge): jumps, drops, grapples
    opens = {}
    for (va, vb), ps in edges.items():
        if len(ps) == 1:
            mid = (v[va] + v[vb]) / 2.0
            opens.setdefault(zone[ps[0]], []).append(mid.astype(np.float64))
    for z in opens:
        opens[z] = np.array(opens[z])
    zl = list(opens.keys())
    zpos = np.array([out_zones[z]["pos"] for z in zl])
    walk_pairs = {(a, b) for (a, b, k) in links if k == "walk"}
    if verts is not None:
        V = verts.astype(np.float64)
        A, E1, E2 = V[tris[:, 0]], V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]]
    for i, za in enumerate(zl):
        pa = opens[za]
        near = np.flatnonzero(np.linalg.norm(zpos[:, [0, 2]] - zpos[i, [0, 2]], axis=1) <= grapple_scan + 2 * ZONE_CELL)
        for j in near:
            zb = zl[j]
            if zb == za or (za, zb) in walk_pairs:
                continue
            pb = opens[zb]
            # nearest pair of open points (flat), for jumps and drops
            d = pa[:, None, :] - pb[None, :, :]
            flat = np.hypot(d[..., 0], d[..., 2])
            up = pb[None, :, 1] - pa[:, None, 1]          # + : zb higher
            k = np.unravel_index(np.argmin(flat + np.abs(up) * 0.25), flat.shape)
            if flat[k] <= LEDGE_GAP:
                if abs(up[k]) <= JUMP_UP:
                    link(za, zb, "jump", pa[k[0]], pb[k[1]])
                elif up[k] < 0 and -up[k] <= LEDGE_DROP * 3:   # down a ledge (falls are survivable well past a step)
                    link(za, zb, "drop", pa[k[0]], pb[k[1]])
                continue
            if verts is None:
                continue
            # grapple: from za (lower) to a lip of zb at least GRAPPLE_MIN_UP higher, in reach and in sight
            cand = np.argwhere((up >= GRAPPLE_MIN_UP) & (np.hypot(flat, up - AIM_UP) <= grapple_scan))
            if not len(cand):
                continue
            dist = np.hypot(flat[cand[:, 0], cand[:, 1]], up[cand[:, 0], cand[:, 1]] - AIM_UP)
            for c in cand[np.argsort(dist)][:GRAPPLE_ZONE_TRIES]:
                o = pa[c[0]] + [0, AIM_UP, 0]
                seg = pb[c[1]] - o
                L = float(np.linalg.norm(seg))
                if L < 1:
                    continue
                if not lp2navgen.ray_hits(A, E1, E2, o, seg / L, L - 30):
                    link(za, zb, "grapple", pa[c[0]], pb[c[1]], length=L)
                    break
    # ladders: both ways between the floors at the foot and the top
    for lo, hi, a, b in ladders:
        if lo in local and hi in local:
            link(zone[local[lo]], zone[local[hi]], "ladder", a, b)
            link(zone[local[hi]], zone[local[lo]], "ladder", b, a)
    # launch: impulse / velocity force volumes that push players, from the floor centre along the trajectory
    g = EARTH * float((p.get("environment") or {}).get("gravity", 1.0))
    for vol in lp2mapc.all_parts(p):
        q = vol.get("force") or {}
        if q.get("mode") not in ("impulse", "velocity") or not q.get("players"):
            continue
        x, y, z = (float(c) * 100.0 for c in q.get("vector", [0, 0, 0]))
        if q.get("local", True):
            r = math.radians(lp2mapc.volume_yaw(vol))
            c_, s_ = math.cos(r), math.sin(r)
            x, z = x * c_ + z * s_, -x * s_ + z * c_
        start = np.array(vol["pos"], dtype=np.float64)
        from_zone = zone[np.argmin(np.linalg.norm(cen - start, axis=1))]
        pos, vel = start + [0, 50, 0], np.array([x, y, z])
        landed = None
        for _ in range(int(12 / LAUNCH_STEP)):   # up to 12 s of flight
            nxt = pos + vel * LAUNCH_STEP
            vel = vel - [0, g * LAUNCH_STEP, 0]
            if vel[1] < 0:   # falling: lands on the first triangle it passes down through
                flat = np.hypot(cen[:, 0] - nxt[0], cen[:, 2] - nxt[2])
                hit = np.flatnonzero((flat < 150) & (cen[:, 1] <= pos[1]) & (cen[:, 1] >= nxt[1] - 5))
                if len(hit):
                    landed = hit[np.argmax(cen[hit, 1])]
                    break
            pos = nxt
            if pos[1] < cen[:, 1].min() - 2000:
                break
        if landed is not None and zone[landed] != from_zone:
            link(from_zone, zone[landed], "launch", start, cen[landed])
    out_links = []
    for (za, zb, kind), (d, a, b) in sorted(links.items()):
        e = {"from": za, "to": zb, "kind": kind, "a": a, "b": b}
        if kind == "grapple":
            e["length"] = round(d, 1)
        out_links.append(e)
    return {"zones": out_zones, "links": out_links}


REMOVE_UP = 200.0   # cm: a brushed point removes polygons whose middle is within this above or below it


def marked(v, poly, among, items, what):
    """the polygons project.json "nav_removed" / "nav_added" items pick among those in `among` (bool per polygon):
    {"brush": [[x, y, z], ...], "r": cm}: middles within r across and REMOVE_UP up / down of a point; then
    {"piece": [x, y, z]}: the whole piece there, of what's left among them, over shared edges only (so a piece welded to
    the main floor goes alone, as the editor shows it) -> bool per polygon"""
    out = np.zeros(len(poly), bool)
    if not isinstance(items, list) or not items:
        return out
    cen = v[poly].mean(1)
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("brush"), list):
            r = float(it.get("r", 300.0))
            for q in it["brush"]:
                q = np.asarray(q, float)
                out |= (np.hypot(cen[:, 0] - q[0], cen[:, 2] - q[2]) <= r) & (np.abs(cen[:, 1] - q[1]) <= REMOVE_UP)
    out &= among
    left = among & ~out
    piece = None
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("piece"), list):
            if piece is None:
                piece = lp2navgen.pieces(poly, (), left)
            cand = np.flatnonzero(left)
            k = lp2navgen.poly_at(v, poly[cand], it["piece"]) if len(cand) else -1
            i = int(cand[k]) if k >= 0 else -1
            if i >= 0 and piece[i] >= 0:
                out |= piece == piece[i]
            else:
                print(f"{what} piece at {it['piece']}: no navmesh there now")
    n = int(out.sum())
    if n:
        print(f"{what} by hand: {n} polygons ({len(items)} item(s))")
    return out


def removed(v, poly, keep, welds, items):
    """project.json "nav_removed": what's taken out of the kept polygons (marked)"""
    return marked(v, poly, keep, items, "removed")

def read_obj(path):
    """the editor's hand-edited navmesh (project.json "nav_mesh"): an OBJ in metres, Y up -> v (n, 3) cm, p (m, 3)
    triangles (polygons fanned; texture / normal indices ignored; degenerate and repeated triangles dropped)"""
    vs, fs = [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        q = line.split()
        if not q:
            continue
        if q[0] == "v" and len(q) >= 4:
            vs.append([float(q[1]), float(q[2]), float(q[3])])
        elif q[0] == "f" and len(q) >= 4:
            ids = [int(x.split("/")[0]) for x in q[1:]]
            ids = [i - 1 if i > 0 else len(vs) + i for i in ids]
            fs += [(ids[0], ids[k], ids[k + 1]) for k in range(1, len(ids) - 1)]
    v = np.array(vs, float).reshape(-1, 3) * 100.0
    p = np.array(fs, np.int64).reshape(-1, 3)
    p = p[(p[:, 0] != p[:, 1]) & (p[:, 1] != p[:, 2]) & (p[:, 0] != p[:, 2])]
    _, first = np.unique(np.sort(p, axis=1), axis=0, return_index=True)
    p = p[np.sort(first)]
    used = np.unique(p)
    remap = np.full(len(v), -1)
    remap[used] = np.arange(len(used))
    return v[used], remap[p]


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
    st = p.get("nav_settings") if isinstance(p.get("nav_settings"), dict) else {}
    agent = {k: float(st[k]) for k in ("climb", "slope", "radius") if isinstance(st.get(k), (int, float))}
    if agent:
        print("navmesh settings: " + ", ".join(f"{k} {x:g}" for k, x in agent.items()))
    hand = p.get("nav_mesh") if isinstance(p.get("nav_mesh"), str) and p.get("nav_mesh") else None
    if hand and os.path.isfile(os.path.join(folder, hand)):
        v, poly = read_obj(os.path.join(folder, hand))
        if len(poly):   # ladders are added below each build: a frozen copy's own (vertical) ones go
            P = v[poly].astype(np.float64)
            nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            poly = poly[np.abs(nrm[:, 1]) > 0.2 * np.linalg.norm(nrm, axis=1)]
        print(f"navmesh: hand-edited {hand} ({len(poly)} triangles; Regenerate in the editor goes back to generating it)")
    else:
        if hand:
            print(f"navmesh: {hand} not found, generating instead")
        v, poly = lp2navgen.generate(verts, tris, agent=agent, solid=st.get("solid", True) is not False)
    if not len(poly):
        raise SystemExit("no walkable surface found in the movement collision")
    print("@progress 0.55 welds", flush=True)
    climb = agent.get("climb", lp2navgen.AGENT["climb"])
    welds = lp2navgen.auto_welds(v, poly, float(st.get("weld", 0) or 0), max(climb, 30.0), verts=verts, tris=tris)
    welds += lp2navgen.manual_welds(v, poly, [w for w in p.get("nav_welds", []) if isinstance(w, dict)])
    v, poly, ladder, lwelds, lad_links = add_ladders(v, poly, [x for x in p.get("ladders", []) if isinstance(x, dict)])
    welds += lwelds
    print("@progress 0.6 playable area", flush=True)
    cen = v[poly].mean(1)
    keep = np.zeros(len(poly), bool)
    pts = markers(folder, p)
    reg = regions(v, poly, verts, tris, welds[:len(welds) - len(lwelds)], skip=ladder, late=lwelds)
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
    keep |= marked(v, poly, ~keep, p.get("nav_added"), "added back")   # left-out parts put back by hand
    keep &= ~removed(v, poly, keep, welds, p.get("nav_removed"))
    prev = os.path.join(folder, ".preview")
    os.makedirs(prev, exist_ok=True)
    piece = lp2navgen.pieces(poly, welds, keep)
    npieces = int(piece.max()) + 1 if keep.any() else 0
    sizes = np.bincount(piece[piece >= 0], minlength=npieces) if npieces else np.zeros(0, int)
    print(f"pieces: {npieces} (polygons in each, largest first: {sizes[:12].tolist()})")
    with open(os.path.join(prev, "navmesh.bin"), "wb") as f:
        f.write(struct.pack("<I", len(poly)))
        f.write(v[poly].astype("<f4").tobytes())
        f.write(keep.astype(np.uint8).tobytes())
        # since the welds (2026-11-13): piece per triangle (u16, 0xffff dropped), then the welds: u32 count,
        # each 2 x (x, y, z) f32 cm (the two edge middles) + u8 (1 placed by hand)
        f.write(np.where(piece < 0, 0xFFFF, piece).astype("<u2").tobytes())
        kw = [w for w in welds if keep[w[0]] and keep[w[2]]]
        f.write(struct.pack("<I", len(kw)))
        for w in kw:
            f.write(np.concatenate([w[4], w[5]]).astype("<f4").tobytes() + struct.pack("<B", 1 if w[6] else 0))
    print("@progress 0.65 zones", flush=True)
    nz = zones_and_links(v, poly, keep, verts, tris, p, welds=welds, ladders=lad_links, skip=ladder)
    json.dump(nz, open(os.path.join(prev, "navzones.json"), "w"))
    kinds = {}
    for e in nz["links"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"zones: {len(nz['zones'])}, links: " + (", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none"))
    kp = poly[keep]
    used = np.unique(kp)
    remap = np.full(len(v), -1)
    remap[used] = np.arange(len(used))
    print("@progress 0.75 waypoints", flush=True)
    tag = (p.get("info") or {}).get("tag") or "custom"
    kidx = np.cumsum(keep) - 1   # full polygon number -> kept number
    kwelds = [(int(kidx[w[0]]), w[1], int(kidx[w[2]]), w[3]) + tuple(w[4:]) for w in welds if keep[w[0]] and keep[w[2]]]
    lnv = lp2navgen.write(os.path.join(folder, "assets", "nav"), tag, v[used], remap[kp], verts, tris, links=nz["links"],
                          welds=kwelds, ladder=ladder[keep])
    rel = lambda f: os.path.relpath(f, folder).replace(os.sep, "/")
    res = dict(lnv=rel(lnv), way=rel(os.path.join(os.path.dirname(lnv), "Way_%s.rAIWayPoint" % tag)),
               polygons=int(keep.sum()), dropped=int((~keep).sum()), zones=len(nz["zones"]), links=len(nz["links"]),
               pieces=npieces, piece_sizes=sizes[:20].tolist(), welds=len(kwelds),
               welds_manual=sum(1 for w in kwelds if w[6]),
               # the hand marks this build applied: the editor previews only ones added since (applied ones are in keep)
               marks={k: [x for x in (p.get(k) or []) if isinstance(x, dict)] for k in ("nav_removed", "nav_added")})
    json.dump(res, open(os.path.join(prev, "navmesh.json"), "w"))
    open(os.path.join(prev, "navmesh.stamp"), "w").write(lp2mapc.nav_stamp(folder))
    print("@result " + json.dumps(res))


if __name__ == "__main__":
    sys.exit(main())
