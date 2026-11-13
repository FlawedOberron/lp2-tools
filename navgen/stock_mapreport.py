# per stock map from the work folder's .preview/navmesh.bin: kept area, main piece share, pieces, big dropped chunks
import sys, os, struct, json, numpy as np
sys.path.insert(0, os.path.expanduser('~/Projects/lp2-tools'))
import lp2navmap
W = os.path.expanduser(sys.argv[1])
def chunks(P, mask):
    idx = np.flatnonzero(mask)
    key = {}
    parent = {i: i for i in idx}
    def f(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in idx:
        for e in range(3):
            a, b = tuple(np.round(P[i, e]).astype(int)), tuple(np.round(P[i, (e+1) % 3]).astype(int))
            k = (min(a, b), max(a, b))
            if k in key: parent[f(i)] = f(key[k])
            else: key[k] = i
    out = {}
    for i in idx: out.setdefault(f(i), []).append(i)
    return list(out.values())
for m in sorted(os.listdir(W)):
    f = os.path.join(W, m, ".preview", "navmesh.bin")
    if not os.path.exists(f): continue
    d = open(f, "rb").read(); n = struct.unpack_from("<I", d)[0]; o = 4
    P = np.frombuffer(d, "<f4", n * 9, o).reshape(n, 3, 3).astype(float); o += n * 36
    keep = np.frombuffer(d, np.uint8, n, o).astype(bool); o += n
    piece = np.frombuffer(d, "<u2", n, o).astype(int)
    area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1) / 1e4
    flat = np.abs(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])[:, 1]) > 1
    kept = keep & flat
    pa = np.bincount(piece[kept], weights=area[kept]) if kept.any() else np.zeros(1)
    big = sorted(pa, reverse=True)
    frag = [a for a in big[1:] if a > 25]
    dropped = sorted(((area[c].sum(), c) for c in chunks(P, ~keep & flat)), key=lambda x: -x[0])
    pts = np.asarray(lp2navmap.markers(os.path.join(W, m), json.load(open(os.path.join(W, m, "project.json")))), float).reshape(-1, 3)
    def near(c):
        lo, hi = P[c].reshape(-1, 3).min(0), P[c].reshape(-1, 3).max(0)
        return int(((pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0]) & (pts[:, 2] >= lo[2]) & (pts[:, 2] <= hi[2]) & (pts[:, 1] >= lo[1] - 100) & (pts[:, 1] <= hi[1] + 400)).sum())
    dropped = [(a, np.round(P[c].reshape(-1, 3).mean(0) / 100).astype(int).tolist(), near(c)) for a, c in dropped if a > 100]
    print(f"{m}: kept {area[kept].sum():.0f} m2, main piece {100 * big[0] / max(pa.sum(), 1e-6):.0f}%, "
          f"other pieces over 25 m2: {len(frag)} ({sum(frag):.0f} m2); dropped chunks over 100 m2: {len(dropped)} "
          + " ".join(f"{a:.0f}m2@{c}/{k}mk" for a, c, k in dropped[:6]))
