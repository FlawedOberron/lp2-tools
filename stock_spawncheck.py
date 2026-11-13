#!/usr/bin/env python3
"""Per stock map in an lp2stocknav work folder: each spawn's floor (the highest up-facing movement collision from
3 m under it to 1 m over it) and whether kept navmesh covers that floor (within 60 cm). Spawns with no floor near
them and floors with no kept navmesh are listed, clustered 15 m (centres in metres).
  stock_spawncheck.py WORK [mapNN ...]"""
import json, os, struct, sys
import numpy as np
import lp2navmap

def main():
    W = os.path.expanduser(sys.argv[1])
    lib = os.path.expanduser("~/Projects/lp2-assets/library")
    maps = sys.argv[2:] or sorted(m for m in os.listdir(W) if m.startswith("map"))
    for m in maps:
        F = os.path.join(W, m)
        p = json.load(open(os.path.join(F, "project.json")))
        lay = json.load(open(os.path.join(F, p["layout"]["file"])))
        pts = sorted({tuple(q["pos"]) for s in lay["sets"] for q in s["points"]})
        verts, tris, _ = lp2navmap.collision(F, lib)
        V = verts.astype(float); A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
        nrm = np.cross(B - A, C - A); ny = nrm[:, 1] / (np.linalg.norm(nrm, axis=1) + 1e-9)
        d = open(os.path.join(F, ".preview", "navmesh.bin"), "rb").read(); n = struct.unpack_from("<I", d)[0]
        P = np.frombuffer(d, "<f4", n * 9, 4).reshape(n, 3, 3).astype(float)
        keep = np.frombuffer(d, np.uint8, n, 4 + n * 36).astype(bool)
        K = P[keep]
        def under(Aa, Bb, Cc, x, z):
            dd = (Bb[:, 2] - Cc[:, 2]) * (Aa[:, 0] - Cc[:, 0]) + (Cc[:, 0] - Bb[:, 0]) * (Aa[:, 2] - Cc[:, 2])
            ok = np.abs(dd) > 1; dd = np.where(ok, dd, 1)
            l1 = ((Bb[:, 2] - Cc[:, 2]) * (x - Cc[:, 0]) + (Cc[:, 0] - Bb[:, 0]) * (z - Cc[:, 2])) / dd
            l2 = ((Cc[:, 2] - Aa[:, 2]) * (x - Cc[:, 0]) + (Aa[:, 0] - Cc[:, 0]) * (z - Cc[:, 2])) / dd
            l3 = 1 - l1 - l2
            return ok & (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3), l1 * Aa[:, 1] + l2 * Bb[:, 1] + l3 * Cc[:, 1]
        nofloor, nonav = [], []
        for x, y, z in pts:
            hit, h = under(A, B, C, x, z)
            sel = hit & (ny > 0.64) & (h >= y - 300) & (h <= y + 100)
            if not sel.any():
                nofloor.append((x, y, z)); continue
            fy = h[sel].max()
            hk, hn = under(K[:, 0], K[:, 1], K[:, 2], x, z)
            if not (hk & (np.abs(hn - fy) <= 60)).any():
                nonav.append((x, fy, z))
        def clusters(l):
            cl = []
            for q in l:
                for g in cl:
                    if np.linalg.norm(np.mean(g, 0) - q) < 1500: g.append(q); break
                else: cl.append([q])
            cl.sort(key=len, reverse=True)
            return "  ".join(f"{len(g)}@{np.round(np.mean(g, 0) / 100).astype(int).tolist()}" for g in cl[:6])
        print(f"{m}: {len(pts)} spawns; no floor near {len(nofloor)} {clusters(nofloor)}")
        print(f"       floor without kept navmesh {len(nonav)} {clusters(nonav)}", flush=True)

if __name__ == "__main__":
    main()
