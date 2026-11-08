#!/usr/bin/env python3
"""Bake a built stage's light into lightmap textures, the way the game's own stages do, instead of into vertex colours:
shadow edges no longer follow the triangles. Called by lp2bake.bake_stage when the project's stage.light.lightmap > 0
(cm per texel).

The game's format, read from the stock stages (2026-11-06; online00 has both kinds side by side):
  vertex format 0xB86DE023, 28 bytes, as 0x49B4F022 except +24: lightmap uv f16x2 (v down, no flip) instead of the colour
  material: word 1 0x144480 -> 0x44440 (0x144880 -> 0x44840), word 6 (the texture slot left empty) -> the lightmap
  texture: 1024 x 1024 DXT1 (format 19), mips, named <stage>-NNN_LM; byte = 2 x the vertex colour for the same light
  (measured on online00's vertices shared by both kinds of mesh), so light 1.0 is white and nothing brighter fits.

Steps: long edges split so every triangle fits a page; triangles grouped into flat charts; charts packed on pages (a
mesh and material for each page they land on); each texel gets the sun and the placed lights by its own rays (sharp),
sky, ground and bounces by rays gathering the vertex bake's light (lp2bake.bake; blurred a little within the chart).
Texels inside walls are thrown away and filled from their neighbours, so no light bleeds in under a wall.
Materials and formats the stock stages never light this way stay vertex lit.
"""
import os, struct
import numpy as np

import lp2bake, lp2stage, lp2tex

FMT = 0xB86DE023
PAGE = 1024
MAX_PAGES = 32
PAD = 2              # empty texels round a chart (so a gap of 4; the blur reaches 2)
FLAT = 0.7           # a triangle joins a chart when its normal is within this cosine of the chart's
LM_WORD1 = {0x144480: 0x44440, 0x144880: 0x44840}
# word 0 values seen with a lightmap in the stock stages
LM_WORD0 = {0x80000043, 0x8000C043, 0x80400043, 0x80004043, 0x80024043, 0x80004083, 0x80028043, 0x80030043, 0x8001C043}
SUN_RAYS = 3         # squared: a grid across the texel, so a shadow's edge is smooth
LIGHT_RAYS = 4
SKY_RAYS = 32
CHUNK = 1 << 19
BLUR = 2             # texels: the box blur (twice) on the sky, ground and bounce light
PLAY_MARGIN = 3000.0 # cm round the layout's markers: what gets the lightmap; beyond (LP1's kilometres of scenery, high roofs) stays vertex lit
BURIED = 0.5         # a texel with fewer than this share of its sky rays starting clear is inside something


def lightable(raw):
    w0, w1, slot = struct.unpack_from("<I", raw, 0)[0], struct.unpack_from("<I", raw, 4)[0], struct.unpack_from("<I", raw, 24)[0]
    return w0 in LM_WORD0 and w1 in LM_WORD1 and slot == 0


def lit_material(raw, tex_slot):
    b = bytearray(raw)
    struct.pack_into("<I", b, 4, LM_WORD1[struct.unpack_from("<I", raw, 4)[0]])
    struct.pack_into("<I", b, 24, tex_slot)
    return bytes(b)


def play_box(folder, p, P, log=print):
    """the area worth texels: (lo x, lo y, lo z), (hi x, hi y, hi z) round the layout's markers; None: everything"""
    import lp2navmap
    try:
        pts = np.asarray(lp2navmap.markers(folder, p), np.float64).reshape(-1, 3)
    except Exception as e:
        log(f"  lightmap: no markers to go by ({e}): the whole stage")
        return None
    if len(pts) < 2:
        log("  lightmap: no markers to go by: the whole stage")
        return None
    return np.percentile(pts, 0.5, axis=0) - PLAY_MARGIN, np.percentile(pts, 99.5, axis=0) + PLAY_MARGIN


def split_long(attrs, T, limit, log=print):
    """midpoint splits until no edge of a triangle is longer than limit (cm)"""
    for _ in range(12):
        P, n = attrs["P"], len(attrs["P"])
        key = np.unique(lp2bake._edges(T, n).ravel())
        a, b = key // n, key % n
        far = np.linalg.norm(P[a] - P[b], axis=1) > limit
        if not far.any():
            break
        attrs, T = lp2bake.split_edges(attrs, T, key[far], np.full(int(far.sum()), 0.5), unit=("N",))
    return attrs, T


def adjacency(P, T, group):
    """-> CSR (start, neighbours) of triangles sharing an edge, by position, within a mesh"""
    key = np.concatenate([np.round(P / 0.5).astype(np.int64), group[:, None].astype(np.int64)], 1)
    weld = np.unique(key, axis=0, return_inverse=True)[1].ravel()
    W = weld[T]
    n = int(weld.max()) + 1
    e = np.sort(np.stack([W[:, [0, 1]], W[:, [1, 2]], W[:, [2, 0]]], 1), 2)
    k = (e[..., 0] * n + e[..., 1]).ravel()
    tri = np.repeat(np.arange(len(T)), 3)
    order = np.argsort(k, kind="stable")
    k, tri = k[order], tri[order]
    same = np.nonzero(k[1:] == k[:-1])[0]
    a, b = tri[same], tri[same + 1]
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    order = np.argsort(src, kind="stable")
    return np.searchsorted(src[order], np.arange(len(T) + 1)), dst[order]


def charts(P, T, group, cm, log=print):
    """-> chart per triangle, per chart (tangent, bitangent, normal) as (c, 3, 3), and (k, 3, 2) texel coordinates
    from a chart's corner, (c, 2) chart sizes in texels with the padding"""
    tri = P[T]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(fn, axis=1)
    fn = fn / np.maximum(area, 1e-9)[:, None]
    start, nb = adjacency(P, T, group)
    start, nb = start.tolist(), nb.tolist()
    limit = (PAGE - 2 * PAD - 2) * cm
    chart = [-1] * len(T)
    FN = fn.tolist()
    TRI = tri.tolist()
    frames = []
    for s in np.argsort(-area).tolist():
        if chart[s] >= 0:
            continue
        c = len(frames)
        n = FN[s]
        t = max(((np.array(TRI[s][i]) - np.array(TRI[s][(i + 1) % 3])) for i in range(3)), key=lambda e: float(e @ e))
        t = t - np.array(n) * float(t @ np.array(n))
        ln = float(np.linalg.norm(t))
        if ln < 1e-9:
            a = np.array([1.0, 0, 0]) if abs(n[0]) < .9 else np.array([0, 1.0, 0])
            t = np.cross(n, a)
            ln = float(np.linalg.norm(t))
        t = t / ln
        b = np.cross(n, t)
        frames.append((t, b, np.array(n)))
        tx, ty, tz, bx, by, bz = *t.tolist(), *b.tolist()
        nx, ny, nz = n
        u = [p[0] * tx + p[1] * ty + p[2] * tz for p in TRI[s]]
        v = [p[0] * bx + p[1] * by + p[2] * bz for p in TRI[s]]
        u0, u1, v0, v1 = min(u), max(u), min(v), max(v)
        chart[s] = c
        stack = [s]
        while stack:
            f = stack.pop()
            for g in nb[start[f]:start[f + 1]]:
                if chart[g] >= 0:
                    continue
                m = FN[g]
                if m[0] * nx + m[1] * ny + m[2] * nz < FLAT:
                    continue
                pts = TRI[g]
                u = [p[0] * tx + p[1] * ty + p[2] * tz for p in pts]
                v = [p[0] * bx + p[1] * by + p[2] * bz for p in pts]
                nu0, nu1, nv0, nv1 = min(u0, *u), max(u1, *u), min(v0, *v), max(v1, *v)
                if nu1 - nu0 > limit or nv1 - nv0 > limit:
                    continue
                u0, u1, v0, v1 = nu0, nu1, nv0, nv1
                chart[g] = c
                stack.append(g)
    chart = np.array(chart)
    F = np.array(frames)
    # corners in the chart's plane
    U = np.einsum("ijk,ik->ij", tri, F[chart, 0])
    V = np.einsum("ijk,ik->ij", tri, F[chart, 1])
    c = len(F)
    lo = np.stack([np.full(c, np.inf), np.full(c, np.inf)], 1)
    hi = -lo
    np.minimum.at(lo[:, 0], chart, U.min(1))
    np.minimum.at(lo[:, 1], chart, V.min(1))
    np.maximum.at(hi[:, 0], chart, U.max(1))
    np.maximum.at(hi[:, 1], chart, V.max(1))
    tuv = np.stack([(U - lo[chart, 0][:, None]) / cm, (V - lo[chart, 1][:, None]) / cm], 2) + PAD
    size = np.ceil((hi - lo) / cm).astype(np.int64) + 2 * PAD + 1
    return chart, F, tuv, size


def pack(size, order_key):
    """shelves, a material at a time (so a material spans as few pages as it can) -> (c, 3) page, x, y; page count"""
    out = np.zeros((len(size), 3), np.int64)
    page, x, y, shelf = 0, 0, 0, 0
    for key in np.unique(order_key):
        ids = np.nonzero(order_key == key)[0]
        ids = ids[np.argsort(-size[ids, 1], kind="stable")]
        if x:   # a new shelf per material
            x, y, shelf = 0, y + shelf, 0
        for c, (w, h) in zip(ids.tolist(), size[ids].tolist()):
            if x + w > PAGE:
                x, y, shelf = 0, y + shelf, 0
            if y + h > PAGE:
                page, x, y, shelf = page + 1, 0, 0, 0
            out[c] = page, x, y
            x += w
            shelf = max(shelf, h)
    return out, page + 1


def raster(uv, page_of, pages):
    """-> per page (tri (H, W) int32, -1 empty; weights (H, W, 3)). A texel takes the nearest triangle within a texel,
    so a triangle's edge texels exist for the filtering; the point used is clamped onto the triangle"""
    out = [(np.full((PAGE, PAGE), -1, np.int32), np.zeros((PAGE, PAGE, 3), np.float32), np.full((PAGE, PAGE), 9.0, np.float32))
           for _ in range(pages)]
    lo = np.floor(uv.min(1) - 1.5).astype(np.int64)
    hi = np.ceil(uv.max(1) + 1.5).astype(np.int64)
    side = (hi - lo).max(1)
    bucket = np.ceil(np.log2(np.maximum(side, 1))).astype(np.int64)
    for bk in np.unique(bucket):
        B = 1 << int(bk)
        ids = np.nonzero(bucket == bk)[0]
        step = max(1, (1 << 20) // (B * B))
        gx = np.arange(B)
        for i in range(0, len(ids), step):
            part = ids[i:i + step]
            a, b, c = uv[part, 0], uv[part, 1], uv[part, 2]
            x = lo[part, 0, None, None] + gx[None, None, :] + 0.5
            y = lo[part, 1, None, None] + gx[None, :, None] + 0.5
            e0, e1 = b - a, c - a
            den = e0[:, 0] * e1[:, 1] - e0[:, 1] * e1[:, 0]
            den = np.where(np.abs(den) < 1e-9, 1e-9, den)[:, None, None]
            px, py = x - a[:, 0, None, None], y - a[:, 1, None, None]
            w1 = (px * e1[:, 1, None, None] - py * e1[:, 0, None, None]) / den
            w2 = (py * e0[:, 0, None, None] - px * e0[:, 1, None, None]) / den
            w1c, w2c = np.clip(w1, 0, 1), np.clip(w2, 0, 1)
            s = w1c + w2c
            over = np.maximum(s, 1.0)
            w1c, w2c = w1c / over, w2c / over
            qx = a[:, 0, None, None] + e0[:, 0, None, None] * w1c + e1[:, 0, None, None] * w2c
            qy = a[:, 1, None, None] + e0[:, 1, None, None] * w1c + e1[:, 1, None, None] * w2c
            d = np.maximum(np.abs(qx - x), np.abs(qy - y))
            # inside counts as distance 0 whatever the rounding says
            inside = (w1 >= 0) & (w2 >= 0) & (w1 + w2 <= 1)
            d = np.where(inside, 0.0, d)
            k, gy_, gx_ = np.nonzero(d <= 1.0)
            if not len(k):
                continue
            X = lo[part[k], 0] + gx_
            Y = lo[part[k], 1] + gy_
            ok = (X >= 0) & (X < PAGE) & (Y >= 0) & (Y < PAGE)
            k, gy_, gx_, X, Y = k[ok], gy_[ok], gx_[ok], X[ok], Y[ok]
            pg = page_of[part[k]]
            dv, w1v, w2v = d[k, gy_, gx_], w1c[k, gy_, gx_], w2c[k, gy_, gx_]
            for p in np.unique(pg):
                tid, wt, dist = out[p]
                on = np.nonzero(pg == p)[0]
                on = on[np.argsort(-dv[on], kind="stable")]   # nearest written last
                yy, xx = Y[on], X[on]
                keep = dv[on] < dist[yy, xx]
                on, yy, xx = on[keep], yy[keep], xx[keep]
                dist[yy, xx] = dv[on]
                tid[yy, xx] = part[k[on]]
                wt[yy, xx, 0] = 1 - w1v[on] - w2v[on]
                wt[yy, xx, 1] = w1v[on]
                wt[yy, xx, 2] = w2v[on]
    return [(t, w) for t, w, _ in out]


def box(img, mask, r):
    """box blur counting only mask's texels (normalised), the result only where mask is"""
    def sat(a):
        return np.pad(a, ((1, 0), (1, 0)) + ((0, 0),) * (a.ndim - 2)).cumsum(0).cumsum(1)
    h, w = mask.shape
    y0 = np.maximum(np.arange(h) - r, 0); y1 = np.minimum(np.arange(h) + r + 1, h)
    x0 = np.maximum(np.arange(w) - r, 0); x1 = np.minimum(np.arange(w) + r + 1, w)
    def rect(s):
        return s[y1][:, x1] - s[y0][:, x1] - s[y1][:, x0] + s[y0][:, x0]
    m = mask.astype(np.float64)
    n = rect(sat(m))
    v = rect(sat(img * m[..., None]))
    out = img.copy()
    on = mask & (n > 0)
    out[on] = (v[on].T / n[on]).T
    return out


def fill(img, mask):
    """colour the texels outside mask from their neighbours (a few rings), the rest with the page's mean: the DXT blocks
    and the mips then have no dark edges"""
    img, done = img.copy(), mask.copy()
    for _ in range(16):
        if done.all():
            break
        s = np.zeros_like(img)
        c = np.zeros(done.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            s += np.roll(np.roll(img * done[..., None], dy, 0), dx, 1)
            c += np.roll(np.roll(done, dy, 0), dx, 1)
        new = ~done & (c > 0)
        img[new] = (s[new].T / c[new]).T
        done |= new
    if not done.all():
        img[~done] = img[done].mean(0) if done.any() else 0.0
    return img


def light_page(tid, wt, A, env, lights, s, rng, tracer, Tocc, X, up_sky, down_ground, cm, chart, frames):
    """-> (H, W, 3) linear light and the mask of the texels that have one"""
    k_sun = lp2bake._col(env.get("sun_colour"), lp2bake.STOCK_SUN) * float(s["sun"])
    k_lights = float(s["lights"])
    P, N, T, FN, emit = A["P"], A["N"], A["T"], A["FN"], A["emit"]
    on_y, on_x = np.nonzero(tid >= 0)
    direct, indirect = np.zeros(tid.shape + (3,), np.float32), np.zeros(tid.shape + (3,), np.float32)
    good = np.zeros(tid.shape, bool)
    sd = lp2bake._sun_dir(env)
    t_s, b_s = lp2bake._frame(sd[None])
    for i in range(0, len(on_y), CHUNK):
        yy, xx = on_y[i:i + CHUNK], on_x[i:i + CHUNK]
        tri, w = tid[yy, xx], wt[yy, xx].astype(np.float64)
        n = len(tri)
        vs = T[tri]
        pos = (P[vs] * w[..., None]).sum(1)
        nrm = (N[vs] * w[..., None]).sum(1)
        fn = FN[tri]
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        fn = np.where(np.linalg.norm(fn, axis=1, keepdims=True) > .5, fn, [[0.0, 1.0, 0.0]])   # degenerate triangles
        nrm = np.where(ln > 1e-3, nrm / np.maximum(ln, 1e-6), fn)
        F = frames[chart[tri]]
        base = pos + fn * lp2bake.EPS

        def origins(idx, cell=(0, 0, 1)):
            cx, cy, grid = cell
            a, b = (rng.random(len(idx)) + cx) / grid - .5, (rng.random(len(idx)) + cy) / grid - .5
            return (base[idx] + F[idx, 0] * (a * cm)[:, None] + F[idx, 1] * (b * cm)[:, None]).astype(np.float32)

        # sky, ground and what the rays hit
        tv, bv = lp2bake._frame(nrm)
        sky, ground, gath = np.zeros(n), np.zeros(n), np.zeros((n, 3))
        valid = np.zeros(n)
        everyone = np.arange(n)
        for k in range(SKY_RAYS):
            u1 = (k + rng.random(n)) / SKY_RAYS
            a = rng.random(n) * 2 * np.pi
            r = np.sqrt(u1)
            d = tv * (r * np.cos(a))[:, None] + bv * (r * np.sin(a))[:, None] + nrm * np.sqrt(1 - u1)[:, None]
            pid, hu, hv = tracer.run(origins(everyone), d.astype(np.float32))
            valid += pid != -2
            miss = pid == -1
            up = d[:, 1] >= 0
            sky += miss & up
            ground += miss & ~up
            hit = np.nonzero(pid >= 0)[0]
            if len(hit):
                c = Tocc[pid[hit]]
                wh = np.stack([1 - hu[hit] - hv[hit], hu[hit], hv[hit]], 1)
                gath[hit] += (X[c] * wh[..., None]).sum(1)
        ok = valid >= BURIED * SKY_RAYS
        wv = 1.0 / np.maximum(valid, 1)
        ind = (np.outer(sky * wv * np.pi, up_sky) + np.outer(ground * wv * np.pi, down_ground) + gath * wv[:, None])
        # the sun
        L = np.zeros((n, 3))
        cos = nrm @ sd
        lit = np.nonzero((cos > 0) & ok)[0]
        if len(lit):
            clear, cnt = np.zeros(len(lit)), np.zeros(len(lit))
            for ray in range(SUN_RAYS * SUN_RAYS):
                r = np.sqrt(rng.random(len(lit))) * lp2bake.SUN_SPREAD
                a = rng.random(len(lit)) * 2 * np.pi
                d = sd + t_s * (r * np.cos(a))[:, None] + b_s * (r * np.sin(a))[:, None]
                d /= np.linalg.norm(d, axis=1, keepdims=True)
                h = tracer.trace(origins(lit, (ray % SUN_RAYS, ray // SUN_RAYS, SUN_RAYS)), d.astype(np.float32))
                clear += h == 0
                cnt += h >= 0
            L[lit] = np.outer(cos[lit] * clear / np.maximum(cnt, 1), k_sun)
        # placed lights
        for li in lights or []:
            lp = np.asarray(li["pos"], np.float64)
            v = lp - pos
            dist = np.linalg.norm(v, axis=1)
            end, start = float(li.get("end", 1000.0)), float(li.get("start", 0.0))
            f = np.clip((end - dist) / max(end - start, 1.0), 0, 1)
            dn = v / np.maximum(dist, 1e-6)[:, None]
            f *= np.clip(np.einsum("ij,ij->i", nrm, dn), 0, None)
            if li.get("type") == "spot" and li.get("dir"):
                half = np.radians(float(li.get("cone", 60.0)) / 2)
                soft = np.radians(float(li.get("spread", 10.0)))
                c = -dn @ np.asarray(li["dir"], np.float64)
                f *= np.clip((c - np.cos(half + soft)) / max(np.cos(half) - np.cos(half + soft), 1e-4), 0, 1)
            idx = np.nonzero((f > 0) & ok)[0]
            if not len(idx):
                continue
            clear = np.zeros(len(idx))
            for _ in range(LIGHT_RAYS):
                o = origins(idx)
                v2 = lp - o
                d2 = np.linalg.norm(v2, axis=1)
                clear += tracer.trace(o, (v2 / np.maximum(d2, 1e-6)[:, None]).astype(np.float32), (d2 - lp2bake.EPS).astype(np.float32)) != 1
            L[idx] += np.outer(f[idx] * clear / LIGHT_RAYS, lp2bake._col(li.get("colour"), [1, 1, 1]) * float(li.get("brightness", 2.0))) * k_lights
        # glowing materials show their glow
        L += emit[A["vmat"][vs[:, 0]]] * float(s["glow"]) * np.pi
        direct[yy, xx] = L
        indirect[yy, xx] = ind
        good[yy, xx] = ok
    for _ in range(2):
        indirect = box(indirect, good, BLUR)
    return direct + indirect, good


def bake(attrs, T, S, albedo, emission, env, lights, s, out_dir, stem, tex_dir, folder, p, log=print):
    """-> textures (names), materials, meshes for lp2stage.write_stage; the lightmap textures written to out_dir.
    attrs as lp2bake.bake_stage's (P, N, TG, U, C, W, vmat, group, optional occ)"""
    cm = float(s["lightmap"])
    can = np.array([lightable(raw) for raw in S["materials"]])
    use_group = np.array([can[m["mat"]] for m in S["meshes"]])
    box_ = play_box(folder, p, attrs["P"], log)
    # coarser until it fits the pages: a first guess from the area, then the real packing
    while True:
        limit = (PAGE - 2 * PAD - 2) * cm * 0.7
        at, Tt = split_long(attrs, T, limit, log)
        tri = at["P"][Tt]
        on = use_group[at["group"][Tt[:, 0]]]
        mid = tri.mean(1)
        on &= np.linalg.norm(mid - np.median(at["P"], 0), axis=1) < lp2bake.FAR
        if box_ is not None:
            on &= (mid >= box_[0]).all(1) & (mid <= box_[1]).all(1)
        used = np.linalg.norm(np.cross(tri[on, 1] - tri[on, 0], tri[on, 2] - tri[on, 0]), axis=1).sum() / 2
        guess = used / (cm * cm) / 0.55 / (PAGE * PAGE)
        if guess > MAX_PAGES:
            cm *= max(1.1, float(np.sqrt(guess / MAX_PAGES)))
            continue
        Tl = Tt[on]
        chart, F, tuv, size = charts(at["P"], Tl, at["group"], cm, log)
        mat_of_chart = np.zeros(len(F), np.int64)
        mat_of_chart[chart] = at["vmat"][Tl[:, 0]]
        where, pages = pack(size, mat_of_chart)
        if pages <= MAX_PAGES:
            break
        cm *= 1.15
    if cm != float(s["lightmap"]):
        log(f"  lightmap: {s['lightmap']} cm a texel doesn't fit {MAX_PAGES} pages: using {cm:.1f}")
    fillrate = float(size.prod(1).sum()) / (pages * PAGE * PAGE)
    log(f"  lightmap: {len(Tl)} triangles of {len(Tt)}, {len(F)} charts, {pages} pages at {cm:.1f} cm a texel ({fillrate:.0%} used)")

    # the vertex bake: what the texels' rays gather, and the light of whatever stays vertex lit
    _, _, comp = lp2bake.bake_detailed(at, Tt, albedo, emission, env, lights, dict(s, detail=0), log)
    L_v = lp2bake.combine(comp, env, s)
    gain = lp2bake.CALIBRATION * 2.0 ** float(s["exposure"])
    tint = np.asarray(s.get("sky_tint") or [1, 1, 1], np.float64) * float(s["sky"])
    up_sky = lp2bake._col(env.get("sky_colour"), lp2bake.STOCK_SKY) * tint
    down_ground = lp2bake._col(env.get("ground_colour"), lp2bake.STOCK_GROUND) * tint
    # outgoing light of each vertex: its colour x the light on it (not counting its own glow) + its own glow
    P32, N32, _ = lp2bake._clean(at["P"], at["N"])
    far_v = ~np.isfinite(comp).all(1)
    occ = at["occ"] > 0.5 if "occ" in at else None
    Tf = Tt[~far_v[Tt].any(1)]
    Tocc = Tf if occ is None else Tf[occ[Tf].all(1)]
    glow_self = emission[at["vmat"]] * np.pi
    c0 = np.nan_to_num(comp).astype(np.float64)
    c0[:, 12:15] -= glow_self
    k_sun = lp2bake._col(env.get("sun_colour"), lp2bake.STOCK_SUN) * float(s["sun"])
    raw = (c0[:, 0:3] * k_sun + c0[:, 3:6] * up_sky + c0[:, 6:9] * down_ground + c0[:, 9:12] * float(s["lights"]) + c0[:, 12:15] * float(s["glow"]))
    X = albedo[at["vmat"]] * float(s["bounce"]) * raw + glow_self * float(s["glow"])

    tracer = lp2bake._Tracer(P32, N32, Tocc)
    fn = np.cross(P32[Tl[:, 1]] - P32[Tl[:, 0]], P32[Tl[:, 2]] - P32[Tl[:, 0]]).astype(np.float64)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
    side = np.sign(np.einsum("ij,ij->i", fn, at["N"][Tl].sum(1)))
    fn *= np.where(side == 0, 1, side)[:, None]
    A = dict(P=at["P"], N=at["N"], T=Tl, FN=fn, emit=emission, vmat=at["vmat"])
    uv = tuv + where[chart, 1:][:, None, :]
    page_of = where[chart, 0]
    rng = np.random.default_rng(1)
    rasters = raster(uv, page_of, pages)

    # the textures
    names = list(S["textures"])
    first_lm = len(names)
    lm_dir = tex_dir
    for p in range(pages):
        lp2bake.progress(0.45 + 0.5 * p / pages, f"lightmap page {p + 1}/{pages}")
        L, good = light_page(*rasters[p], A, env, lights, s, rng, tracer, Tocc, X, up_sky, down_ground, cm, chart, F)
        L = L * gain
        m = float(s["min_light"])
        L = np.sqrt(L * L + m * m)
        byte = np.clip(np.power(np.maximum(L, 0), 1 / 2.2), 0, 1) * 255.0
        byte = fill(byte, good)
        rgba = np.dstack([np.round(byte).astype(np.uint8), np.full(byte.shape[:2], 255, np.uint8)])
        nm = f"{stem}-{p:03d}_LM"
        open(os.path.join(out_dir, nm + ".rTexture"), "wb").write(lp2tex.encode(rgba, "bm", mips=6))
        names.append(lm_dir + "\\" + nm)

    # the materials: the stage's own, then one per (material, page)
    materials = list(S["materials"])
    lit_mats = {}
    def lit(mat, page):
        k = (mat, page)
        if k not in lit_mats:
            lit_mats[k] = len(materials)
            materials.append(lit_material(S["materials"][mat], first_lm + page + 1))
        return lit_mats[k]

    # the vertices
    L = lp2bake.combine(comp, env, s)
    good_v = np.isfinite(L).all(1)
    col = np.clip(np.round(at["C"]), 0, 255).astype(np.uint8)
    col[good_v, :3] = np.round(lp2bake.to_colour(L[good_v]) * 255).astype(np.uint8)
    pack8 = lambda x: np.clip(np.round(x * 127.0 + 127.0), 0, 255).astype(np.uint8)
    rows = np.zeros((len(col), 28), np.uint8)
    rows[:, :12] = at["P"].astype("<f4").view(np.uint8).reshape(-1, 12)
    rows[:, 12:15], rows[:, 15] = pack8(at["N"]), at["W"][:, 0]
    rows[:, 16:19], rows[:, 19] = pack8(at["TG"]), at["W"][:, 1]
    rows[:, 20:24] = at["U"].astype("<f2").view(np.uint8).reshape(-1, 4)
    rows[:, 24:28] = col

    meshes = []
    tg = at["group"][Tt[:, 0]]
    tgl = at["group"][Tl[:, 0]]
    for k, m in enumerate(S["meshes"]):
        ts = Tt[(tg == k) & ~on]
        if len(ts):
            vi, inv = np.unique(ts, return_inverse=True)
            meshes.append(dict(mat=m["mat"], verts=rows[vi], tris=inv.reshape(-1, 3)))
        sel = np.nonzero(tgl == k)[0]
        if not len(sel):
            continue
        for p in np.unique(page_of[sel]):
            part = sel[page_of[sel] == p]
            # a vertex per (vertex, chart)
            key = np.stack([Tl[part].ravel(), np.repeat(chart[part], 3)], 1)
            uniq, inv = np.unique(key, axis=0, return_inverse=True)
            inv = inv.ravel()
            v = rows[uniq[:, 0]].copy()
            first = np.zeros(len(uniq), np.int64)
            first[inv] = np.arange(len(inv))
            coords = uv[part].reshape(-1, 2)[first] / PAGE
            v[:, 24:28] = coords.astype("<f2").view(np.uint8).reshape(-1, 4)
            meshes.append(dict(mat=lit(m["mat"], int(p)), verts=v, tris=inv.reshape(-1, 3), fmt=FMT))
    log(f"  lightmap: {len(meshes)} meshes, {len(materials)} materials ({len(materials) - len(S['materials'])} lit)")
    return names, materials, meshes, pages
