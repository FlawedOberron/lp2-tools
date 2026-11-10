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


def zones_and_links(v, poly, keep, verts, tris, p, grapple_scan=GRAPPLE_SCAN):
    """The playable navmesh cut into zones (bots route zone to zone) and the links between them, each with how it's
    crossed: walk (shared edge, both ways), jump (a gap or step up to JUMP_UP, both ways), drop (down a ledge, one way),
    grapple (up to a higher lip in sight, one way; "length" so bots skip ones beyond the match's anchor range) and launch
    (an impulse / velocity force volume to where its trajectory lands, one way). Zones: manual zone volumes ("zone":
    name) first, the rest cut on a ZONE_CELL grid, each walkable patch in a cell its own zone (so floors differ).
    -> {zones: [{name, pos, size}], links: [{from, to, kind, a, b, length?}]}"""
    idx = np.flatnonzero(keep)
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
    print("@progress 0.65 zones", flush=True)
    nz = zones_and_links(v, poly, keep, verts, tris, p)
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
    lnv = lp2navgen.write(os.path.join(folder, "assets", "nav"), tag, v[used], remap[kp], verts, tris, links=nz["links"])
    rel = lambda f: os.path.relpath(f, folder).replace(os.sep, "/")
    res = dict(lnv=rel(lnv), way=rel(os.path.join(os.path.dirname(lnv), "Way_%s.rAIWayPoint" % tag)),
               polygons=int(keep.sum()), dropped=int((~keep).sum()), zones=len(nz["zones"]), links=len(nz["links"]))
    json.dump(res, open(os.path.join(prev, "navmesh.json"), "w"))
    open(os.path.join(prev, "navmesh.stamp"), "w").write(lp2mapc.nav_stamp(folder))
    print("@result " + json.dumps(res))


if __name__ == "__main__":
    sys.exit(main())
