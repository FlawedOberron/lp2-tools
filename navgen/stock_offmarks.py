# per map: markers with no navmesh polygon under them, clustered (15 m), centre in m and count
import sys, os, struct, json, numpy as np
sys.path.insert(0, os.path.expanduser('~/Projects/lp2-tools'))
import lp2navmap
W = os.path.expanduser(sys.argv[1])
for m in sys.argv[2:]:
    F = os.path.join(W, m)
    d = open(os.path.join(F, ".preview", "navmesh.bin"), "rb").read(); n = struct.unpack_from("<I", d)[0]
    P = np.frombuffer(d, "<f4", n * 9, 4).reshape(n, 3, 3).astype(float)
    keep = np.frombuffer(d, np.uint8, n, 4 + n * 36).astype(bool)
    v = P[keep].reshape(-1, 3); p = np.arange(len(v)).reshape(-1, 3)
    pts = np.asarray(lp2navmap.markers(F, json.load(open(os.path.join(F, "project.json")))), float).reshape(-1, 3)
    a, b, c = v[p[:, 0]], v[p[:, 1]], v[p[:, 2]]
    dd = (b[:, 2] - c[:, 2]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 2] - c[:, 2]); ok = np.abs(dd) > 1; dd = np.where(ok, dd, 1)
    off = []
    for x, y, z in pts:
        l1 = ((b[:, 2] - c[:, 2]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (z - c[:, 2])) / dd
        l2 = ((c[:, 2] - a[:, 2]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (z - c[:, 2])) / dd
        l3 = 1 - l1 - l2; h = l1 * a[:, 1] + l2 * b[:, 1] + l3 * c[:, 1]
        if not (ok & (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3) & (h >= y - 300) & (h <= y + 100)).any():
            off.append((x, y, z))
    cl = []
    for q in off:
        for g in cl:
            if np.linalg.norm(np.mean(g, 0) - q) < 1500: g.append(q); break
        else: cl.append([q])
    cl.sort(key=len, reverse=True)
    print(f"{m}: {len(off)} of {len(pts)} markers off the kept navmesh:", "  ".join(f"{len(g)}@{np.round(np.mean(g, 0) / 100).astype(int).tolist()}" for g in cl[:8]))
