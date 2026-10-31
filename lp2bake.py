#!/usr/bin/env python3
"""Bake a stage's vertex light: the sun (soft shadows), the sky, the project's placed lights, glowing materials and
light bounces (radiosity), ray traced with Embree (pip package embreex). Replaces the LP1 lightmap bake that
lp2stage.py samples into the vertex colour, when the project's stage.light.source is "bake".

  lp2bake.py PROJECT_DIR             bake the editor's preview (.preview/geo.bin + bake.bin; the unsplit LP1 one kept
                                     in geo_base.bin / .json)
  lp2bake.py PROJECT_DIR --restore   the preview back to the LP1 bake

lp2mapc.py bakes the built stage (after the editor's geometry edits) the same way; lp2preview.py re-bakes a rebuilt
preview. Settings, project stage.light (defaults in DEFAULTS): source "lp1" / "bake"; live: sun, sky (strengths),
sky_tint, lights, glow, exposure (EV), min_light (the darkest linear light allowed, softly); baked: bounce (strength),
bounces, samples (sky rays per vertex), emissive {colour map name: [r, g, b]} (glowing materials).
The bake keeps each light source apart (COMPONENTS, bounces included: light adds up), so the live settings and the
sun / sky / ground colours apply afterwards without a re-bake (combine(); the editor's shader, from .preview/bake.bin).
Geometry, light placement, sun direction, bounces and samples need a re-bake.

Light model (the editor's baked.gdshader; assumed to be the game's): the vertex colour c is light in gamma space,
pixel = colour map x (2c)^2.2, so linear light L = (2c)^2.2 and c = L^(1/2.2) / 2 (L 1.0 = byte 128). Sun, sky and
ground colours come from the project's environment (as the Lighting window shows them). Bounced light takes each
material's average colour-map colour. Stage units are cm; the preview's are m.
"""
import argparse, hashlib, json, os, shutil, sys, warnings
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = dict(source="lp1", sun=0.4, sky=1.0, sky_tint=[1.0, 1.0, 1.0], lights=1.0, glow=1.0, exposure=0.0,
                min_light=0.01, bounce=1.0, bounces=2, samples=64, detail=0, emissive={})
LIVE = ("sun", "sky", "sky_tint", "lights", "glow", "exposure", "min_light")   # applied to the stored components
STOCK_SUN, STOCK_SKY, STOCK_GROUND = [2.43] * 3, [0.152] * 3, [0.106] * 3
CALIBRATION = 0.48    # linear light per unit of irradiance (fitted: Battlegrounds' default bake's median = LP1's)
EPS = 2.0             # ray start off the surface, cm
FAR = 200000.0        # cm from the map's centre: beyond it (LP1's sky dome, ~3-7 km out) nothing blocks light or is baked
SUN_SAMPLES = 8
SUN_SPREAD = 0.01     # soft shadow: rays within this many radians of the sun direction
SPREAD = 0.6          # rays start up to this far from a vertex towards the middle of a triangle around it
CHUNK = 1 << 20
PART = 1 << 15         # rays per thread job (embree releases the GIL: rays trace on every core)
COMPONENTS = ("sun", "sky", "ground", "lights", "glow")
# detail (settings "detail": up to that many % more vertices, over 100 allowed). Each pass: find where the sun's
# shadow line crosses the edges (shadow_splits: the sun traced along every edge, a vertex put each side of the line),
# then with the budget left, quick-bake and split the triangles whose corners' other light (sky, placed lights,
# bounces: doorways, wall feet) differs most; DETAIL_PASSES passes (one more per 50%), then the full bake
DETAIL_PASSES = 3
DETAIL_SAMPLES = 16
DETAIL_CONTRAST = 0.4    # split when the brightest corner is over e^0.4 (1.5x) the darkest
DETAIL_MIN_EDGE = 30.0   # cm: edges shorter than this aren't split
EDGE_STEP = 10.0         # cm between the sun tests along an edge, EDGE_MIN_SAMPLES to EDGE_MAX_SAMPLES of them
EDGE_MIN_SAMPLES, EDGE_MAX_SAMPLES = 4, 48
PROBE = 10.0             # cm: the second crossing test beside each one (the shadow line's direction)
EDGE_REFINE = 5          # bisection steps on each shadow crossing found (to 1/256 of the edge)
SHADOW_PAIR = 12.0       # cm: the vertices either side of a shadow line are this far from it (a sharp step)
# position edges (_EdgeSet): an edge's copies in other blocks / at seams split alike (no T-junction cracks)
SHARP_REACH = 4.0        # cm: those vertices' rays start at most this far from them (not across the line)
END_GAP = 6.0            # cm: no new vertex this close to an edge's end (the end stands in for it)


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(os.cpu_count() or 4)
    return _POOL


def settings(p):
    s = dict(DEFAULTS)
    s.update((p.get("stage") or {}).get("light") or {})
    return s


def progress(f, text):
    print(f"@progress {f:.3f} {text}", flush=True)


def srgb_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def albedo_png(path):
    """a colour map's average colour (linear), from a preview PNG"""
    from PIL import Image
    try:
        im = Image.open(path).convert("RGB")
    except OSError:
        return None
    im.thumbnail((64, 64))
    return srgb_lin(np.asarray(im, np.float64) / 255.0).reshape(-1, 3).mean(0)


def _frame(n):
    """tangent, bitangent for unit normals (n, 3)"""
    a = np.where(np.abs(n[:, :1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
    t = np.cross(n, a)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    return t, np.cross(n, t)


def _col(c, fallback):
    return np.asarray(c if c is not None else fallback, np.float64)


class _Tracer:
    """an Embree scene of P[T]; run() / trace() split the rays over the threads"""

    def __init__(self, P, N, T):
        from embreex import rtcore_scene as rtcs
        from embreex.mesh_construction import TriangleMesh
        self.scene = rtcs.EmbreeScene()
        TriangleMesh(self.scene, P[T])
        tri_n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
        front = np.sign(np.einsum("ij,ij->i", tri_n, N[T].sum(1)))   # which side of each triangle its vertices face
        self.tri_n = tri_n * front[:, None]

    def run(self, o, d, dist=None):
        """-> primID (-2: the ray started behind a surface), u, v"""
        pid, u, v = np.empty(len(o), np.int32), np.empty(len(o), np.float32), np.empty(len(o), np.float32)

        def part(i):
            sl = slice(i, i + PART)
            dd = None if dist is None else np.ascontiguousarray(dist[sl], np.float32)
            dp = np.ascontiguousarray(d[sl], np.float32)
            h = self.scene.run(np.ascontiguousarray(o[sl], np.float32), dp, dists=dd, output=1)
            p = h["primID"]
            back = (p >= 0) & (np.einsum("ij,ij->i", self.tri_n[np.maximum(p, 0)], d[sl]) > 0)
            pid[sl], u[sl], v[sl] = np.where(back, -2, p), h["u"], h["v"]
        list(_pool().map(part, range(0, len(o), PART)))
        return pid, u, v

    def trace(self, o, d, dist=None):
        """-> 1 blocked, 0 clear, -1 the ray started behind a surface (inside a wall: the sample doesn't count)"""
        pid = self.run(o, d, dist)[0]
        return np.where(pid == -2, -1, pid >= 0).astype(np.int8)


def _clean(P, N):
    """float32 copies, broken normals pointing up; -> P, N, far (beyond FAR: not traced or baked)"""
    P, N = P.astype(np.float32), N.astype(np.float32).copy()
    bad = ~np.isfinite(N).all(1) | (np.linalg.norm(N, axis=1) < 0.5)
    N[bad] = (0, 1, 0)
    return P, N, np.linalg.norm(P - np.median(P, 0), axis=1) > FAR


def _sun_dir(env):
    sd = np.asarray(env.get("sun") or [0.472, 0.848, 0.241], np.float64)
    return sd / np.linalg.norm(sd)


def bake(P, N, T, vmat, albedo, emission, env, lights, s, log=print, reach=None):
    """-> light components per vertex (n, 15): COMPONENTS x rgb, before the live settings (combine());
    NaN for the far geometry (it keeps its old colour). The sun, sky and ground are white here (their colours
    are live), the placed lights and glow carry their own colours. Bounces are in every component.
    P (n, 3) cm, N (n, 3) unit normals, T (k, 3) triangles, vmat (n,) material per vertex, albedo / emission
    (materials, 3) linear, env the project's environment, lights its placed lights, s settings(); reach (n,) cm:
    how far from each vertex its rays may start at most (None: no limit)."""
    P, N, far = _clean(P, N)
    T = T[~far[T].any(1)]
    tracer = _Tracer(P, N, T)
    run, trace = tracer.run, tracer.trace
    n = len(P)
    rng = np.random.default_rng(1)
    # each ray starts somewhere on the surface around its vertex (towards the centre of one of its triangles), so a
    # vertex's light is its neighbourhood's, like a lightmap texel; from the corner itself, floors at the foot of a
    # wall all fell into the wall's shadow
    order = np.argsort(T.ravel(), kind="stable")
    vt = order // 3                                           # triangles by vertex
    first = np.searchsorted(T.ravel()[order], np.arange(n))
    count = np.bincount(T.ravel(), minlength=n)
    centre = P[T].mean(1)

    def origins(idx):
        c = count[idx]
        pick = vt[np.minimum(first[idx] + (rng.random(len(idx)) * c).astype(np.int64), len(vt) - 1)]
        f = np.where(c > 0, rng.random(len(idx)) * SPREAD, 0.0)[:, None]
        off = (centre[pick] - P[idx]) * f
        if reach is not None:
            ln = np.linalg.norm(off, axis=1)
            off *= np.minimum(1.0, reach[idx] / np.maximum(ln, 1e-6))[:, None]
        return (P[idx] + off + N[idx] * EPS).astype(np.float32)

    C = np.zeros((n, 15))
    # direct: the sun (white, unit strength)
    progress(0.03, "sun")
    sd = _sun_dir(env)
    cos = N @ sd
    lit = np.nonzero(cos > 0)[0]
    clear, valid = np.zeros(len(lit)), np.zeros(len(lit))
    t, b = _frame(sd[None])
    for _ in range(SUN_SAMPLES):
        r = np.sqrt(rng.random(len(lit))) * SUN_SPREAD
        a = rng.random(len(lit)) * 2 * np.pi
        d = sd + t * (r * np.cos(a))[:, None] + b * (r * np.sin(a))[:, None]
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        h = trace(origins(lit), d)
        clear += h == 0
        valid += h >= 0
    C[lit, 0:3] = (cos[lit] * clear / np.maximum(valid, 1))[:, None]

    # direct: placed lights (point / spot: full to start, linear fade to end, cm; spots: cone + soft edge)
    for k, L in enumerate(lights or []):
        progress(0.08, f"light {k + 1}")
        lp = np.asarray(L["pos"], np.float64)
        v = lp - P
        dist = np.linalg.norm(v, axis=1)
        end, start = float(L.get("end", 1000.0)), float(L.get("start", 0.0))
        f = np.clip((end - dist) / max(end - start, 1.0), 0, 1)
        d = v / np.maximum(dist, 1e-6)[:, None]
        f *= np.clip(np.einsum("ij,ij->i", N, d), 0, None)
        if L.get("type") == "spot" and L.get("dir"):
            half = np.radians(float(L.get("cone", 60.0)) / 2)
            soft = np.radians(float(L.get("spread", 10.0)))
            c = -d @ np.asarray(L["dir"], np.float64)
            f *= np.clip((c - np.cos(half + soft)) / max(np.cos(half) - np.cos(half + soft), 1e-4), 0, 1)
        on = np.nonzero(f > 0)[0]
        if len(on):
            o = origins(on)
            v2 = lp - o
            d2 = np.linalg.norm(v2, axis=1)
            f[on[trace(o, v2 / np.maximum(d2, 1e-6)[:, None], d2 - EPS) == 1]] = 0
        C[:, 9:12] += np.outer(f, _col(L.get("colour"), [1, 1, 1]) * float(L.get("brightness", 2.0)))

    # sky rays (cosine weighted, fixed per vertex): what each sees, reused by every bounce
    K = int(s["samples"])
    tv, bv = _frame(N.astype(np.float64))
    hit_p = np.full((n, K), -1, np.int32)
    hit_uv = np.zeros((n, K, 2), np.float16)
    valid = np.zeros(n)
    for k in range(K):
        progress(0.1 + 0.6 * k / K, f"sky rays {k + 1}/{K}")
        u1 = (k + rng.random(n)) / K   # stratified on the elevation
        a = rng.random(n) * 2 * np.pi
        r = np.sqrt(u1)
        d = tv * (r * np.cos(a))[:, None] + bv * (r * np.sin(a))[:, None] + N * np.sqrt(1 - u1)[:, None]
        pid, hu, hv = run(origins(np.arange(n)), d)   # -2: started behind a surface, the sample doesn't count
        hit_p[:, k] = pid
        hit_uv[:, k, 0], hit_uv[:, k, 1] = hu, hv
        valid += pid != -2
        miss = pid == -1
        up = d[:, 1] >= 0
        C[:, 3:6] += (miss & up)[:, None] * np.pi
        C[:, 6:9] += (miss & ~up)[:, None] * np.pi
    w_v = 1.0 / np.maximum(valid, 1)
    C[:, 3:9] *= w_v[:, None]

    # bounces: each sky ray that hit a surface gathers that point's outgoing light (albedo x light + glow).
    # Light adds up, so each component bounces on its own; the gather is a fixed sparse sum (owner <- 3 vertices),
    # done for all components at once, rows split over the threads (CSR: the owners are in order).
    progress(0.72, "bounces")
    T32 = T.astype(np.int32)
    hitm = hit_p >= 0
    cnt = hitm.sum(1)
    starts = np.concatenate([[0], np.cumsum(cnt)]) * 3   # each vertex's entries: 3 per sky ray that hit
    cols, wts = np.empty(starts[-1], np.int32), np.empty(starts[-1])

    def entries(r0):
        r1 = min(r0 + 16384, n)
        m, a, b = hitm[r0:r1], starts[r0], starts[r1]
        cols[a:b] = T32[hit_p[r0:r1][m]].ravel()
        w = hit_uv[r0:r1][m].astype(np.float32)
        wv = np.repeat(w_v[r0:r1], cnt[r0:r1])
        wts[a:b] = (np.stack([1 - w[:, 0] - w[:, 1], w[:, 0], w[:, 1]], 1) * wv[:, None]).ravel()
    list(_pool().map(entries, range(0, n, 16384)))
    del hit_p, hit_uv, hitm, T32

    def gather(X):
        """X (n, c) outgoing light -> what each vertex's sky rays gather"""
        out = np.zeros_like(X)

        def rows(r0):
            r1 = min(r0 + 4096, n)
            a, b = starts[r0], starts[r1]
            if a == b:
                return
            prod = X[cols[a:b]] * wts[a:b, None]
            st = starts[r0:r1] - a
            full = starts[r0 + 1:r1 + 1] > starts[r0:r1]
            out[r0:r1][full] = np.add.reduceat(prod, st[full], axis=0)
        list(_pool().map(rows, range(0, n, 4096)))
        return out

    alb = np.tile(albedo[vmat] * s["bounce"], 5)
    glow = emission[vmat] * np.pi
    D = C.copy()
    D[:, 12:15] = gather(glow)   # glow: what the glowing surfaces light around them, then bounced
    on = np.nonzero(D.any(0))[0]   # components with any light (no placed lights or glow: those stay dark)
    E = D.copy()
    for it in range(int(s["bounces"])):
        E[:, on] = D[:, on] + gather(np.ascontiguousarray(alb[:, on] * E[:, on]))
        progress(0.72 + 0.23 * (it + 1) / max(int(s["bounces"]), 1), f"bounce {it + 1}")
    C = E
    C[:, 12:15] += glow   # glowing surfaces show their glow

    # seams: vertices at one spot facing the same way (split by material / atom) share their light
    key = np.concatenate([np.round(P / 0.5).astype(np.int64), np.round(N * 4).astype(np.int64)], 1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    for ci in range(15):
        C[:, ci] = np.bincount(inv, C[:, ci], len(cnt))[inv] / cnt[inv]
    C[far] = np.nan
    progress(0.97, "done")
    return C.astype(np.float32)


def combine(C, env, s):
    """components -> linear light with the live settings (the editor's baked.gdshader does the same)"""
    sun = _col(env.get("sun_colour"), STOCK_SUN) * float(s["sun"])
    tint = np.asarray(s.get("sky_tint") or [1, 1, 1], np.float64) * float(s["sky"])
    L = (C[:, 0:3] * sun + C[:, 3:6] * _col(env.get("sky_colour"), STOCK_SKY) * tint
         + C[:, 6:9] * _col(env.get("ground_colour"), STOCK_GROUND) * tint
         + C[:, 9:12] * float(s["lights"]) + C[:, 12:15] * float(s["glow"]))
    L = L * CALIBRATION * 2.0 ** float(s["exposure"])
    m = float(s["min_light"])   # the floor: a soft max, so the darkest spots lift without going flat
    return np.sqrt(L * L + m * m)


def _edges(T, n):
    """-> (k, 3) edge keys of each triangle's edges (a * n + b, a < b), corners 0-1, 1-2, 2-0"""
    e = np.sort(np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], 1), 2)
    return e[..., 0] * n + e[..., 1]


def _flat(a, b, c):
    """-> twice the area of triangle abc (tuples)"""
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    w = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
    cr = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    return (cr[0] * cr[0] + cr[1] * cr[1] + cr[2] * cr[2]) ** 0.5, u, w


def _ear_clip(poly, P, side=None, band=()):
    """a convex polygon (vertex ids in winding order, edge points collinear with the corners) -> triangles, same
    winding: each step clips the best-shaped ear that isn't flat and doesn't leave the rest flat. P: id -> (x, y, z);
    side: id -> 0 / 1 (shadowed / lit; missing: either): ears mixing sides only between band vertices (the pairs
    either side of a shadow line), unless no other ear is left"""
    poly, out = list(poly), []
    side = side or {}

    def apart(tri):
        s = {side[x] for x in tri if x in side}
        return len(s) > 1 and not all(x in band for x in tri)
    while len(poly) > 3:
        m = len(poly)
        area = [_flat(P[poly[i - 1]], P[poly[i]], P[poly[(i + 1) % m]]) for i in range(m)]
        eps = 1e-6 * max(a for a, _, _ in area)
        best, bq = -1, -1.0
        for i in range(m):
            ar, u, w = area[i]
            if ar <= eps:
                continue
            # the rest stays a polygon if a corner other than i's neighbours (whose angles change) isn't flat, or
            # a neighbour's new corner isn't
            rest = [area[j][0] > eps for j in range(m) if j not in (i, (i - 1) % m, (i + 1) % m)]
            if not any(rest) and m > 3:
                pa, pb = poly[i - 2], poly[i - 1]
                nb, nc = poly[(i + 1) % m], poly[(i + 2) % m]
                if (_flat(P[pa], P[pb], P[nb])[0] <= eps) and (_flat(P[pb], P[nb], P[nc])[0] <= eps):
                    continue
            x = (u[0] + w[0], u[1] + w[1], u[2] + w[2])
            q = ar / (sum(v * v for v in u) + sum(v * v for v in w) + sum(v * v for v in x) + 1e-12)
            if apart((poly[i - 1], poly[i], poly[(i + 1) % m])):
                q -= 1.0   # only when nothing else is left
            if q > bq:
                best, bq = i, q
        if best < 0:
            return out
        out.append([poly[best - 1], poly[best], poly[(best + 1) % m]])
        del poly[best]
    if _flat(*(P[i] for i in poly))[0] > 0:
        out.append(poly)
    return out


def split_edges(attrs, T, key, t, unit=("N",), side=None, band=None):
    """new vertices on edges: key (m,) the edge (a * n + b, a < b), t (m,) how far along from a (several on one edge
    allowed). Each triangle with points on its edges is cut up (ear clipping its corners and edge points); the
    triangles either side of an edge share its new vertices (no cracks). attrs: name -> per-vertex array (new
    vertices interpolated, the unit ones renormalised; integer arrays copy the nearer end); side (n + m,) 0 / 1 / NaN
    and band (n + m,) bool: see _ear_clip. -> attrs, T; the new vertices are n.. in key's order"""
    P = attrs["P"]
    n, m = len(P), len(key)
    if not m:
        return attrs, T
    a, b = key // n, key % n
    new = {}
    for name, v in attrs.items():
        if np.issubdtype(v.dtype, np.integer):
            x = np.where((t < 0.5).reshape((-1,) + (1,) * (v.ndim - 1)), v[a], v[b])
        else:
            w = t.reshape((-1,) + (1,) * (v.ndim - 1))
            x = v[a].astype(np.float64) * (1 - w) + v[b] * w
            if name in unit:
                x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)
        new[name] = np.concatenate([v, x.astype(v.dtype)])
    on = {}                                                                    # edge key -> [(t, id)] by t
    for k, tt, i in sorted(zip(key.tolist(), t.tolist(), range(n, n + m))):
        on.setdefault(k, []).append(i)
    ek = _edges(T, n)
    marked = np.isin(ek, key).any(1)
    out = [T[~marked]]
    used = np.unique(np.concatenate([T[marked].ravel(), np.arange(n, n + m)]))
    Pn = dict(zip(used.tolist(), new["P"][used].tolist()))
    sd, bd = {}, set()
    if side is not None:
        k = used[np.isfinite(side[used])]
        sd = dict(zip(k.tolist(), side[k].astype(int).tolist()))
        bd = set(used[band[used]].tolist())
    for tri, kk in zip(T[marked].tolist(), ek[marked].tolist()):
        poly = []
        for j in range(3):
            u, w = tri[j], tri[(j + 1) % 3]
            poly.append(u)
            pts = on.get(kk[j], [])
            poly.extend(pts if u < w else pts[::-1])
        tris = _ear_clip(poly, Pn, sd, bd)
        if tris:
            out.append(np.asarray(tris, T.dtype))
    return new, np.concatenate([np.asarray(x, T.dtype).reshape(-1, 3) for x in out])


class _EdgeSet:
    """the triangles' edges grouped by position: an edge's copies (in the next block, or at a UV / normal seam) get
    the same new points, so there are no T-junction cracks between them. Position edges run from the end with the
    lower weld id; a, b: one copy's vertex ids, in that order"""

    def __init__(self, P, T):
        n = self.n = len(P)
        W = self.W = np.unique(np.round(P / 0.5).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
        self.ki = ki = np.unique(_edges(T, n))
        a, b = ki // n, ki % n
        self.flip = flip = W[a] > W[b]
        lo, hi = np.where(flip, b, a), np.where(flip, a, b)
        _, first, iw = np.unique(W[lo].astype(np.int64) * n + W[hi], return_index=True, return_inverse=True)
        self.iw = iw = iw.ravel()
        self.a, self.b = lo[first], hi[first]
        self.count = np.bincount(iw, minlength=len(first))
        self.members = np.argsort(iw, kind="stable")
        self.start = np.cumsum(self.count) - self.count

    def tri_edges(self, T):
        """-> (k, 3) the position edge of each triangle edge (as _edges)"""
        return self.iw[np.searchsorted(self.ki, _edges(T, self.n))]

    def expand(self, we, t):
        """points on position edges (t from their a) -> index edge keys and t for every copy, and each one's point"""
        c = self.count[we]
        src = np.repeat(np.arange(len(we)), c)
        ie = self.members[np.repeat(self.start[we], c) + np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)]
        return self.ki[ie], np.where(self.flip[ie], 1 - t[src], t[src]), src


def shadow_splits(P, N, T, env, sharp, es):
    """where the sun's shadow lines cross the edges (position edges of es): the sun traced every EDGE_STEP along each
    edge facing it, each change between lit and shadowed narrowed down by bisection, the line's direction found by a
    second crossing PROBE beside it, and a vertex put SHADOW_PAIR from the line on either side; and triangles with a
    shadow (or lit) island inside that their edges miss get their longest edge's midpoint. sharp (n,) bool: vertices
    already on a shadow line (the edges between two aren't searched again).
    -> we (position edges), t, pair (bool: a shadow-line vertex), side (each point's: 1 lit, 0 shadowed, NaN
    unknown) and vside (n,) the vertices' sides (see _ear_clip); best first (longest edges)"""
    n = len(P)
    P, N, far = _clean(P, N)
    Tt = T[~far[T].any(1)]
    empty = (np.zeros(0, np.int64), np.zeros(0), np.zeros(0, bool), np.zeros(0), np.full(n, np.nan))
    if not len(Tt):
        return empty
    tracer = _Tracer(P, N, Tt)
    sd = _sun_dir(env)
    sd32 = sd.astype(np.float32)
    a, b, W = es.a, es.b, es.W
    E = len(a)
    D = P[b].astype(np.float64) - P[a]
    ln = np.linalg.norm(D, axis=1)
    sharp_w = np.bincount(W, sharp, W.max() + 1) > 0
    facing = (N[a] @ sd > 0) | (N[b] @ sd > 0)
    look = np.nonzero(facing & ~far[a] & ~far[b] & (ln > DETAIL_MIN_EDGE) & ~(sharp_w[W[a]] & sharp_w[W[b]]))[0]
    m = np.clip(np.ceil(ln / EDGE_STEP), EDGE_MIN_SAMPLES, EDGE_MAX_SAMPLES).astype(np.int64)

    def vis(p, nn):
        """points, unit normals -> 1 lit, 0 shadowed, NaN (facing away, or the test started inside a wall)"""
        h = tracer.trace((p + nn * EPS).astype(np.float32), np.broadcast_to(sd32, p.shape))
        return np.where((nn @ sd > 0) & (h >= 0), (h == 0).astype(np.float64), np.nan)

    def normal(ei, t):
        w = t[:, None]
        nn = N[a[ei]] * (1 - w) + N[b[ei]] * w
        return nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-6)

    def lit(ei, t):
        return vis(P[a[ei]] + D[ei] * t[:, None], normal(ei, t))

    V = np.full((E, EDGE_MAX_SAMPLES), np.nan)
    for j in range(EDGE_MAX_SAMPLES):
        sel = look[m[look] > j]
        if not len(sel):
            break
        V[sel, j] = lit(sel, (j + 0.5) / m[sel])
    change = np.isfinite(V[:, 1:]) & np.isfinite(V[:, :-1]) & (V[:, 1:] != V[:, :-1])
    ei, j = np.nonzero(change)
    lo, hi, v0 = (j + 0.5) / m[ei], (j + 1.5) / m[ei], V[ei, j]
    for _ in range(EDGE_REFINE):
        mid = (lo + hi) / 2
        same = lit(ei, mid) == v0
        lo, hi = np.where(same, mid, lo), np.where(same, hi, mid)
    tc = (lo + hi) / 2

    # the line's direction: beside the crossing (PROBE across the edge, in the surface), find it again along a
    # parallel to the edge; the pair goes SHADOW_PAIR from the line, so along the edge by SHADOW_PAIR / sin(angle)
    e = D[ei] / ln[ei, None]
    nn = normal(ei, tc)
    across = np.cross(nn, e)
    across /= np.maximum(np.linalg.norm(across, axis=1, keepdims=True), 1e-6)
    q = P[a[ei]] + D[ei] * tc[:, None] + across * PROBE
    R = PROBE * 4                                                              # finds lines down to ~14 deg off the edge
    s_lo, s_hi = np.full(len(ei), -R), np.full(len(ei), R)
    w_lo, w_hi = vis(q - e * R, nn), vis(q + e * R, nn)
    found = np.isfinite(w_lo) & np.isfinite(w_hi) & (w_lo != w_hi)
    for _ in range(EDGE_REFINE + 1):
        mid = (s_lo + s_hi) / 2
        same = vis(q + e * mid[:, None], nn) == w_lo
        s_lo, s_hi = np.where(same, mid, s_lo), np.where(same, s_hi, mid)
    line = across * PROBE + e * ((s_lo + s_hi) / 2)[:, None]
    sin = np.linalg.norm(np.cross(e, line), axis=1) / np.maximum(np.linalg.norm(line, axis=1), 1e-6)
    sin = np.where(found, np.maximum(sin, 0.3), 1.0)
    d = SHADOW_PAIR / sin / ln[ei]

    wes, ts, score, pair, sides = [], [], [], [], []
    for sgn in (-1, 1):
        tt = tc + sgn * d
        ok = (tt * ln[ei] > END_GAP) & ((1 - tt) * ln[ei] > END_GAP)
        wes.append(ei[ok]), ts.append(tt[ok]), score.append(ln[ei[ok]]), pair.append(np.ones(ok.sum(), bool))
        sides.append(v0[ok] if sgn < 0 else 1 - v0[ok])
    # each vertex's side: the tests nearest it on its edges (both sides: unknown, a line passes close by)
    nw = W.max() + 1
    sm, sc = np.zeros(nw), np.zeros(nw)
    for end, col in ((W[a], V[:, 0]), (W[b], V[np.arange(E), m - 1])):
        f = np.isfinite(col)
        np.add.at(sm, end[f], col[f]), np.add.at(sc, end[f], 1)
    with np.errstate(all="ignore"):
        vside = (sm / sc)[W]
    vside[~np.isin(vside, (0.0, 1.0))] = np.nan

    # islands: no change along a triangle's edges, but one inside (4 tests: the middle and towards each corner)
    te = es.tri_edges(Tt)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ref = np.nanmean(np.nanmean(V, 1)[te], 1)                              # each triangle's edges' mean
    tl = ln[te]
    cand = np.nonzero(~change.any(1)[te].any(1) & np.isfinite(ref) & (tl.max(1) > DETAIL_MIN_EDGE))[0]
    island = np.zeros(len(cand), bool)
    tri = Tt[cand]
    for bc in ((1 / 3, 1 / 3, 1 / 3), (2 / 3, 1 / 6, 1 / 6), (1 / 6, 2 / 3, 1 / 6), (1 / 6, 1 / 6, 2 / 3)):
        p = P[tri[:, 0]] * bc[0] + P[tri[:, 1]] * bc[1] + P[tri[:, 2]] * bc[2]
        nb = N[tri[:, 0]] * bc[0] + N[tri[:, 1]] * bc[1] + N[tri[:, 2]] * bc[2]
        h = vis(p, nb / np.maximum(np.linalg.norm(nb, axis=1, keepdims=True), 1e-6))
        island |= np.isfinite(h) & (h != (ref[cand] > 0.5))
    c = cand[island]
    longest = np.unique(te[c, tl[c].argmax(1)])
    wes.append(longest), ts.append(np.full(len(longest), 0.5)), score.append(ln[longest] / 2)
    pair.append(np.zeros(len(longest), bool)), sides.append(np.full(len(longest), np.nan))
    we, t, score, pair, side = (np.concatenate(x) for x in (wes, ts, score, pair, sides))
    o = np.lexsort((t, we))                                                    # two crossings close together:
    near = np.zeros(len(o), bool)                                              # no points too close
    near[1:] = (we[o][1:] == we[o][:-1]) & ((t[o][1:] - t[o][:-1]) * ln[we[o][1:]] < END_GAP)
    keep = np.sort(o[~near])
    we, t, score, pair, side = we[keep], t[keep], score[keep], pair[keep], side[keep]
    order = np.argsort(-score, kind="stable")
    return we[order], t[order], pair[order], side[order], vside


def contrast_splits(P, T, L, es, skip):
    """the longest edge's midpoint of each triangle whose corners' light L (n,) differs over DETAIL_CONTRAST (log),
    most contrast x length first, leaving out the position edges in skip. -> we (position edges of es), t"""
    te = es.tri_edges(T)
    ln = np.linalg.norm(P[T[:, [1, 2, 0]]] - P[T], axis=2)                    # (k, 3), as _edges
    lg = np.log(L + 0.01)
    score = lg[T].max(1) - lg[T].min(1) - DETAIL_CONTRAST
    pick = np.nonzero(np.isfinite(score) & (score > 0) & (ln.max(1) > DETAIL_MIN_EDGE))[0]
    pick = pick[np.argsort(-(score[pick] * ln.max(1)[pick]), kind="stable")]
    we = te[pick, ln[pick].argmax(1)]
    _, first = np.unique(we, return_index=True)
    we = we[np.sort(first)]
    we = we[~np.isin(we, skip)]
    return we, np.full(len(we), 0.5)


def detail_passes(detail):
    return DETAIL_PASSES + int(float(detail) // 50)


def bake_detailed(attrs, T, albedo, emission, env, lights, s, log=print):
    """bake() with the detail passes: -> attrs, T (split), components. attrs needs P (cm), N, vmat, group (the
    vertex's block / mesh: kept together by the caller); anything else is carried along"""
    budget = int(len(attrs["P"]) * float(s.get("detail") or 0) / 100)
    reach = np.full(len(attrs["P"]), np.inf)
    for it in range(detail_passes(s.get("detail") or 0) if budget > 0 else 0):
        es = _EdgeSet(attrs["P"], T)
        we, t, pair, side, vside = shadow_splits(attrs["P"], attrs["N"], T, env, np.isfinite(reach), es)
        fit = np.cumsum(es.count[we]) <= budget                                # whole points (every copy) only
        we, t, pair, side = we[fit], t[fit], pair[fit], side[fit]
        left = budget - int(es.count[we].sum())
        if left > 0:
            quick = dict(s, samples=min(DETAIL_SAMPLES, int(s["samples"])), bounces=min(1, int(s["bounces"])))
            comp = bake(attrs["P"], attrs["N"], T, attrs["vmat"], albedo, emission, env, lights, quick, log, reach)
            cw, ct = contrast_splits(attrs["P"], T, combine(comp, env, dict(s, sun=0.0)).mean(1), es, we)
            fit = np.cumsum(es.count[cw]) <= left
            we, t = np.concatenate([we, cw[fit]]), np.concatenate([t, ct[fit]])
            pair = np.concatenate([pair, np.zeros(fit.sum(), bool)])
            side = np.concatenate([side, np.full(fit.sum(), np.nan)])
        key, tt, src = es.expand(we, t)
        band = np.concatenate([np.isfinite(reach), pair[src]])
        reach = np.concatenate([reach, np.where(pair[src], SHARP_REACH, np.inf)])
        attrs, T = split_edges(attrs, T, key, tt, side=np.concatenate([vside, side[src]]), band=band)
        budget -= len(key)
        log(f"detail pass {it + 1}: +{len(key)} vertices ({int(pair[src].sum())} on shadow lines)")
        if not len(key) or budget <= 0:
            break
    comp = bake(attrs["P"], attrs["N"], T, attrs["vmat"], albedo, emission, env, lights, s, log,
                reach if np.isfinite(reach).any() else None)
    return attrs, T, comp


def regroup(attrs, T):
    """vertices sorted by group (stable): -> attrs, T, and per group (first vertex, count)"""
    order = np.argsort(attrs["group"], kind="stable")
    inv = np.empty_like(order)
    inv[order] = np.arange(len(order))
    attrs = {k: v[order] for k, v in attrs.items()}
    return attrs, inv[T], order


def to_colour(L):
    """linear light -> vertex colour 0..1 (c = L^(1/2.2) / 2)"""
    return np.clip(np.power(np.maximum(L, 0), 1 / 2.2) / 2, 0, 1)


def emission_table(names, s):
    em = np.zeros((len(names), 3))
    for i, nm in enumerate(names):
        c = (s.get("emissive") or {}).get(nm or "")
        if c:
            em[i] = c[:3]
    return em


# ---------------------------------------------------------------- the editor's preview

def preview_arrays(prev, name="geo"):
    g = json.load(open(os.path.join(prev, name + ".json")))
    b = open(os.path.join(prev, name + ".bin"), "rb").read()
    arr = lambda k, w, t="<f4": np.frombuffer(b, t, g["arrays"][k][1] // 4, g["arrays"][k][0]).reshape(-1, w)
    P, N, C = arr("pos", 3) * 100.0, arr("nrm", 3), arr("col", 4)
    idx = arr("idx", 3, "<i4").astype(np.int64)
    vmat = np.zeros(len(P), np.int64)
    for atom, mat, v0, vn, i0, ic in g["blocks"]:
        idx[i0 // 3:(i0 + ic) // 3] += v0
        vmat[v0:v0 + vn] = mat
    return g, P, N, C, idx, vmat


def bake_preview(folder, log=print):
    """bake into PROJECT/.preview: bake.bin (the components, see write_custom) and geo.bin / geo.json (split by the
    detail passes; col combined with the current settings, for everything that reads the plain colour). The unsplit
    preview (with the LP1 bake) stays in geo_base.bin / .json: every bake starts from it, restore_preview puts it back"""
    import lp2project
    p = lp2project.load(folder)
    s = settings(p)
    env = p.get("environment") or {}
    prev = os.path.join(folder, ".preview")
    old = os.path.join(prev, "col_lp1.bin")   # an earlier bake's keep of the LP1 colours: back into geo.bin first
    if os.path.exists(old) and not os.path.exists(os.path.join(prev, "geo_base.bin")):
        o, nb = json.load(open(os.path.join(prev, "geo.json")))["arrays"]["col"]
        with open(os.path.join(prev, "geo.bin"), "r+b") as f:
            f.seek(o)
            f.write(open(old, "rb").read()[:nb])
    if os.path.exists(old):
        os.remove(old)
    for ext in ("bin", "json"):
        if not os.path.exists(os.path.join(prev, "geo_base." + ext)):
            shutil.copyfile(os.path.join(prev, "geo." + ext), os.path.join(prev, "geo_base." + ext))
    g, P, N, C, T, vmat = preview_arrays(prev, "geo_base")
    raw = open(os.path.join(prev, "geo_base.bin"), "rb").read()
    U = np.frombuffer(raw, "<f4", g["arrays"]["uv"][1] // 4, g["arrays"]["uv"][0]).reshape(-1, 2)
    group = np.zeros(len(P), np.int64)
    for k, (atom, mat, v0, vn, i0, ic) in enumerate(g["blocks"]):
        group[v0:v0 + vn] = k
    mats = g["materials"]
    albedo = np.stack([a if a is not None else np.full(3, 0.5) for a in
                       (albedo_png(os.path.join(prev, m["tex"])) if m.get("tex") else None for m in mats)]).astype(np.float64)
    attrs = dict(P=P.astype(np.float64), N=N.astype(np.float64), U=U, C=C, vmat=vmat, group=group)
    attrs, T, comp = bake_detailed(attrs, T, albedo, emission_table([m.get("name") for m in mats], s),
                                   env, p.get("lights") or [], s, log)
    order = np.argsort(attrs["group"], kind="stable")   # back into blocks
    attrs, T, comp = {k: v[order] for k, v in attrs.items()}, np.argsort(order)[T], comp[order]
    T = T[np.argsort(attrs["group"][T[:, 0]], kind="stable")]
    write_custom(os.path.join(prev, "bake.bin"), comp)
    L = combine(comp, env, s)
    col = np.array(attrs["C"], np.float32)
    ok = np.isfinite(L).all(1)
    col[ok, :3] = to_colour(L[ok])
    nb = len(g["blocks"])
    v0 = np.searchsorted(attrs["group"], np.arange(nb))
    vn = np.bincount(attrs["group"], minlength=nb)
    tg = attrs["group"][T[:, 0]]
    t0 = np.searchsorted(tg, np.arange(nb))
    tc = np.bincount(tg, minlength=nb)
    local = T - v0[tg][:, None]
    cur = json.load(open(os.path.join(prev, "geo.json")))   # keep what other tools added to it
    arrays, bin_ = {}, bytearray()
    for name, arr in (("pos", attrs["P"] / 100.0), ("nrm", attrs["N"]), ("uv", attrs["U"]), ("col", col), ("idx", local.ravel())):
        data = np.asarray(arr).astype("<i4" if name == "idx" else "<f4").tobytes()
        arrays[name] = [len(bin_), len(data)]
        bin_ += data
    cur["arrays"] = arrays
    cur["blocks"] = [[blk[0], blk[1], int(v0[k]), int(vn[k]), int(t0[k]) * 3, int(tc[k]) * 3] for k, blk in enumerate(g["blocks"])]
    cur.setdefault("stats", {}).update(vertices=int(len(attrs["P"])), triangles=int(len(T)))
    open(os.path.join(prev, "geo.bin"), "wb").write(bin_)
    json.dump(cur, open(os.path.join(prev, "geo.json"), "w"), separators=(",", ":"))
    ref = np.power(np.clip(C[:, :3] * 2, 0, None), 2.2)
    log(f"bake: median light {np.nanmedian(L):.3f} (LP1 bake {np.median(ref):.3f}); "
        f"{len(attrs['P'])} vertices ({len(attrs['P']) - len(P):+d} for detail)")


def write_custom(path, comp):
    """the components as the editor's 4 vertex channels (CUSTOM0-3, RGBA f32, one block each, geo.bin's order):
    sun rgb + 1 (0: not baked, keep the plain colour), sky rgb + glow r, ground rgb + glow g, lights rgb + glow b"""
    ok = np.isfinite(comp).all(1).astype(np.float32)
    c = np.nan_to_num(comp).astype(np.float32)
    blocks = [np.c_[c[:, 0:3], ok], np.c_[c[:, 3:6], c[:, 12]], np.c_[c[:, 6:9], c[:, 13]], np.c_[c[:, 9:12], c[:, 14]]]
    open(path, "wb").write(b"".join(b.astype("<f4").tobytes() for b in blocks))


def read_custom(path):
    """write_custom's file -> components (n, 15), NaN where not baked"""
    b = np.fromfile(path, "<f4").reshape(4, -1, 4)
    comp = np.concatenate([b[0, :, :3], b[1, :, :3], b[2, :, :3], b[3, :, :3], b[1:, :, 3].T], 1)
    comp[b[0, :, 3] < 0.5] = np.nan
    return comp


def restore_preview(folder, log=print):
    prev = os.path.join(folder, ".preview")
    if os.path.exists(os.path.join(prev, "bake.bin")):
        os.remove(os.path.join(prev, "bake.bin"))
    if os.path.exists(os.path.join(prev, "geo_base.bin")):
        cur = json.load(open(os.path.join(prev, "geo.json")))
        base = json.load(open(os.path.join(prev, "geo_base.json")))
        cur.update(arrays=base["arrays"], blocks=base["blocks"])
        cur.setdefault("stats", {}).update(vertices=base["stats"]["vertices"], triangles=base["stats"]["triangles"])
        shutil.copyfile(os.path.join(prev, "geo_base.bin"), os.path.join(prev, "geo.bin"))
        json.dump(cur, open(os.path.join(prev, "geo.json"), "w"), separators=(",", ":"))
        for ext in ("bin", "json"):
            os.remove(os.path.join(prev, "geo_base." + ext))
        log("preview back to the LP1 bake")


# ---------------------------------------------------------------- the built stage (lp2mapc.py)

def bake_stage(model, folder, p, log=print):
    """re-light (and with detail, split) a written stage rModel in place"""
    import lp2pieces, lp2stage
    S = lp2pieces.read_stage(model)
    s = settings(p)
    env = p.get("environment") or {}
    V = np.concatenate([m["v"] for m in S["meshes"]])
    Ts, base = [], 0
    for m in S["meshes"]:
        Ts.append(m["tris"] + base)
        base += len(m["v"])
    unpack = lambda o: (V[:, o:o + 3].astype(np.float64) - 127.0) / 127.0
    attrs = dict(P=V[:, :12].copy().view("<f4").reshape(-1, 3).astype(np.float64), N=unpack(12), TG=unpack(16),
                 U=V[:, 20:24].copy().view("<f2").reshape(-1, 2).astype(np.float64), C=V[:, 24:28].astype(np.float64),
                 W=V[:, [15, 19]].astype(np.int64),
                 vmat=np.concatenate([np.full(len(m["v"]), m["mat"]) for m in S["meshes"]]),
                 group=np.concatenate([np.full(len(m["v"]), k) for k, m in enumerate(S["meshes"])]))
    attrs["N"] /= np.maximum(np.linalg.norm(attrs["N"], axis=1, keepdims=True), 1e-6)
    names = []
    for raw in S["materials"]:
        slot = int.from_bytes(raw[12:16], "little")
        names.append(S["textures"][slot - 1].split("\\")[-1] if 0 < slot <= len(S["textures"]) else None)
    tex = os.path.join(folder, ".preview", "tex")
    albedo = np.stack([a if a is not None else np.full(3, 0.5) for a in
                       (albedo_png(os.path.join(tex, nm + ".png")) if nm else None for nm in names)]).astype(np.float64)
    n0 = len(V)
    # caches (cache_dir()): the whole result, and (without detail) the ray-traced components, which the LIVE
    # settings and the sun / sky / ground colours don't change
    lights = p.get("lights") or []
    model_bytes = open(model, "rb").read()
    ray_inputs = dict(s={k: v for k, v in s.items() if k not in LIVE and k != "source"}, sun=env.get("sun"), lights=lights)
    key_comp = _key(model_bytes, albedo.tobytes(), ray_inputs)
    key_full = _key(model_bytes, albedo.tobytes(), s, lights, {k: env.get(k) for k in ("sun", "sun_colour", "sky_colour", "ground_colour")})
    full = os.path.join(cache_dir(), key_full + ".rModel")
    if os.path.exists(full):
        open(model, "wb").write(open(full, "rb").read())
        log("  baked light: unchanged, from the cache")
        return
    comp_file = os.path.join(cache_dir(), key_comp + ".npy")
    T = np.concatenate(Ts)
    if not float(s.get("detail") or 0) and os.path.exists(comp_file):
        comp = np.load(comp_file)
        log("  baked light: rays unchanged (from the cache), colours re-applied")
    else:
        attrs, T, comp = bake_detailed(attrs, T, albedo, emission_table(names, s), env, lights, s, log)
        if not float(s.get("detail") or 0):
            _cache_put(comp_file, comp)
    L = combine(comp, env, s)
    ok = np.isfinite(L).all(1)
    c = np.clip(np.round(attrs["C"]), 0, 255).astype(np.uint8)
    c[ok, :3] = np.round(to_colour(L[ok]) * 255).astype(np.uint8)
    pack = lambda x: np.clip(np.round(x * 127.0 + 127.0), 0, 255).astype(np.uint8)
    rows = np.zeros((len(c), 28), np.uint8)
    rows[:, :12] = attrs["P"].astype("<f4").view(np.uint8).reshape(-1, 12)
    rows[:, 12:15], rows[:, 15] = pack(attrs["N"]), attrs["W"][:, 0]
    rows[:, 16:19], rows[:, 19] = pack(attrs["TG"]), attrs["W"][:, 1]
    rows[:, 20:24] = attrs["U"].astype("<f2").view(np.uint8).reshape(-1, 4)
    rows[:, 24:28] = c
    tg = attrs["group"][T[:, 0]]
    meshes = []
    for k, m in enumerate(S["meshes"]):
        vi = np.nonzero(attrs["group"] == k)[0]
        remap = np.full(len(rows), -1, np.int64)
        remap[vi] = np.arange(len(vi))
        meshes.append(dict(mat=m["mat"], verts=rows[vi], tris=remap[T[tg == k]]))
    data = lp2stage.write_stage(model, S["textures"], S["materials"], meshes)
    _cache_put(full, data)
    log(f"  baked light: {len(rows)} vertices ({len(rows) - n0:+d} for detail)")


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "lp2-tools", "bake")


def _key(*parts):
    """a cache key over parts (bytes, or anything JSON) and this file's code"""
    h = hashlib.sha1(open(os.path.abspath(__file__), "rb").read())
    for x in parts:
        h.update(x if isinstance(x, bytes) else json.dumps(x, sort_keys=True).encode())
        h.update(b"\0")
    return h.hexdigest()


def _cache_put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    if isinstance(data, np.ndarray):
        with open(tmp, "wb") as f:
            np.save(f, data)
    else:
        open(tmp, "wb").write(data)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    (restore_preview if a.restore else bake_preview)(a.project)


if __name__ == "__main__":
    main()
