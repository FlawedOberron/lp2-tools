#!/usr/bin/env python3
"""Havok MOPP code (the BV tree over map physics triangles): writer, and a reader for checking it.

  lp2mopp.py HAV.bin      read an LP1/LP2 physics file's mesh + MOPP, check it, rebuild it and check that

Decoded from LP1's havs921 (every byte reached, every triangle found by a query at its centroid). Points are
quantised to 24 bits per axis: q = (p - info.xyz) * info.w. The VM keeps an offset o (per axis) and a shift
s (starts 16); an axis value is v = (q - o) >> s, 0..255. Opcodes (big-endian operands, jumps from the
next instruction):
  01-04 k, bx by bz      rescale: o += b << s, s -= k
  05 / 06 / 07 j         jump, 8 / 16 / 24-bit
  09 / 0A d, 0B d        terminal base += d (8 / 16-bit), = d (32-bit)
  10-12 a b j            x / y / z split: v <= a: the next instruction; v >= b: + j (both when they overlap)
  13-1C a b j            the same on diagonal axes (not written here)
  20-22 a j              single plane split (not written here)
  23-25 a b j1 j2        split with 16-bit jumps (v <= a: + j1, v >= b: + j2; not written here)
  26-28 lo hi            x / y / z bounds: outside -> stop
  30-4F                  terminal 0-31 (+ base); 50-53 n bytes: terminal n (+ base)
A terminal is the hkpSimpleMeshShape triangle index.
"""
import struct, sys
import numpy as np

FULL = (1 << 24) - 1
TOL = 0.1    # metres each triangle's box grows by (shape radius, queries' own slack)


def build(verts, tris):
    """verts (n, 3) metres, tris (m, 3) indices -> (info (x, y, z, scale), code bytes)"""
    V = np.asarray(verts, np.float64).reshape(-1, 3)
    T = np.asarray(tris, np.int64).reshape(-1, 3)
    P = V[T]
    lo_m, hi_m = P.min(1) - TOL, P.max(1) + TOL
    off = lo_m.min(0) - 0.01
    scale = FULL / ((hi_m.max(0) - off).max() + 0.01)
    lo = np.clip(np.floor((lo_m - off) * scale), 0, FULL).astype(np.int64)
    hi = np.clip(np.floor((hi_m - off) * scale), 0, FULL).astype(np.int64)
    cen = lo + hi

    def term(i):
        if i < 32:
            return bytes([0x30 + i])
        n = 1 if i < 0x100 else 2 if i < 0x10000 else 3
        return bytes([0x4F + n]) + i.to_bytes(n, "big")

    def bounds(vl, vh):
        return b"".join(bytes([0x26 + a, int(vl[:, a].min()), int(vh[:, a].max())]) for a in range(3))

    def emit(idx, o, s):
        vl, vh = (lo[idx] - o) >> s, (hi[idx] - o) >> s
        if len(idx) == 1:
            return term(int(idx[0]))
        mn, span = vl.min(0), (vh.max(0) - vl.min(0) + 1).max()
        k = 0
        while k < 4 and k < s and span << (k + 1) <= 256:
            k += 1
        if k:   # zoom in: more precision for this subtree
            return bounds(vl, vh) + bytes([k, *(int(x) for x in mn)]) + emit(idx, o + (mn << s), s - k)
        c = cen[idx]
        ax = int(np.argmax(c.max(0) - c.min(0)))
        idx = idx[np.argsort(c[:, ax], kind="stable")]
        h = len(idx) // 2
        L, R = idx[:h], idx[h:]
        a, b = int(((hi[L, ax] - o[ax]) >> s).max()), int(((lo[R, ax] - o[ax]) >> s).min())
        head = bounds(vl, vh) if len(idx) <= 4 else b""
        lc, rc = emit(L, o, s), emit(R, o, s)
        if len(lc) <= 0xFF:
            return head + bytes([0x10 + ax, a, b, len(lc)]) + lc + rc
        jl = b"\x06" + len(rc).to_bytes(2, "big") if len(rc) <= 0xFFFF else b"\x07" + len(rc).to_bytes(3, "big")
        return head + bytes([0x10 + ax, a, b, len(jl)]) + jl + rc + lc

    sys.setrecursionlimit(10000)
    idx = np.arange(len(T))
    o = np.zeros(3, np.int64)
    root = bounds((lo - o) >> 16, (hi - o) >> 16)
    return (float(off[0]), float(off[1]), float(off[2]), float(scale)), root + emit(idx, o, 16)


def query(code, q):
    """terminals a quantised point q (x, y, z) reaches"""
    out, stack = set(), [(0, 0, (0, 0, 0), 16)]
    while stack:
        pc, base, o, s = stack.pop()
        while True:
            op = code[pc]
            v = lambda a: (q[a] - o[a]) >> s
            if 0x01 <= op <= 0x04:
                o = tuple(o[i] + (code[pc + 1 + i] << s) for i in range(3))
                s -= op
                pc += 4
            elif op in (5, 6, 7):
                n = op - 4
                pc += 1 + n + int.from_bytes(code[pc + 1:pc + 1 + n], "big")
            elif op in (9, 10):
                n = op - 8
                base += int.from_bytes(code[pc + 1:pc + 1 + n], "big")
                pc += 1 + n
            elif op == 0x0B:
                base = int.from_bytes(code[pc + 1:pc + 5], "big")
                pc += 5
            elif 0x10 <= op <= 0x1C:
                if op <= 0x12:
                    x = v(op - 0x10)
                    go_l, go_r = x <= code[pc + 1], x >= code[pc + 2]
                else:
                    go_l = go_r = True     # diagonal: both (a superset is still a correct check)
                if go_r:
                    stack.append((pc + 4 + code[pc + 3], base, o, s))
                if not go_l:
                    break
                pc += 4
            elif 0x20 <= op <= 0x22:
                stack.append((pc + 3 + code[pc + 2], base, o, s))
                pc += 3
            elif 0x23 <= op <= 0x25:
                x = v(op - 0x23)
                if x >= code[pc + 2]:
                    stack.append((pc + 7 + int.from_bytes(code[pc + 5:pc + 7], "big"), base, o, s))
                if x > code[pc + 1]:
                    break
                pc += 7 + int.from_bytes(code[pc + 3:pc + 5], "big")
            elif 0x26 <= op <= 0x28:
                x = v(op - 0x26)
                if x < code[pc + 1] or x > code[pc + 2]:
                    break
                pc += 3
            elif 0x30 <= op <= 0x4F:
                out.add(base + op - 0x30)
                break
            elif 0x50 <= op <= 0x53:
                n = op - 0x4F
                out.add(base + int.from_bytes(code[pc + 1:pc + 1 + n], "big"))
                break
            else:
                raise ValueError(f"unknown MOPP opcode {op:#x} at {pc}")
    return out


def check(verts, tris, info, code, sample=None):
    """(found, tested): queries at triangle centroids that reach their own triangle"""
    V = np.asarray(verts, np.float64).reshape(-1, 3)
    T = np.asarray(tris, np.int64).reshape(-1, 3)
    ids = range(len(T)) if sample is None else np.random.default_rng(1).choice(len(T), min(sample, len(T)), replace=False)
    found = 0
    for i in ids:
        q = tuple(int(x) for x in np.floor((V[T[i]].mean(0) - info[:3]) * info[3]))
        found += int(i) in query(code, q)
    return found, len(ids)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    import lp2havok
    verts, tris, info, code = lp2havok.read(open(sys.argv[1], "rb").read())
    print(f"{len(tris)} triangles; stock MOPP {len(code)} bytes: {check(verts, tris, info, code, 2000)} found")
    info, code = build(verts, tris)
    f, n = check(verts, tris, info, code)
    print(f"rebuilt MOPP {len(code)} bytes: {f} of {n} found")
    if f != n:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
