import os, struct, sys, collections
root = sys.argv[1]; stats = collections.defaultdict(list); bad = []
for d, _, fs in os.walk(root):
    for f in fs:
        if not f.endswith('.rTexture'): continue
        b = open(os.path.join(d, f), 'rb').read()
        if b[:4] != b'TEX\0': bad.append(('magic', f)); continue
        ver = struct.unpack_from('<H', b, 4)[0]
        d2, d3, d4 = struct.unpack_from('<III', b, 8)
        typ = d2 & 0xf; mips = (d2 >> 4) & 0x1f; w = (d2 >> 17) & 0x1fff  # guess: bits 10-16 unknown
        mid = (d2 >> 10) & 0x7f
        h = d3 & 0x1fff; cnt = (d3 >> 13) & 0xff; fmt = d4 & 0xff; rest = d4 >> 8
        faces = 6 if typ == 6 else 1  # guess
        n = mips * faces
        offs = struct.unpack_from(f'<{n}I', b, 0x14) if 0x14 + 4*n <= len(b) else ()
        ok = bool(offs) and offs[0] == 0x14 + 4*n
        bpp = (len(b) - (0x14 + 4*n)) / max(1, sum(max(1, w >> i) * max(1, h >> i) for i in range(mips)) * faces)
        stats[(fmt, typ)].append((ok, round(bpp, 3)))
        if not ok: bad.append((f, ver, hex(d2), hex(d3), hex(d4), typ, mips, w, h, len(b)))
for k in sorted(stats):
    v = stats[k]; print(k, len(v), 'ok', sum(o for o, _ in v), 'bpp', collections.Counter(x for _, x in v).most_common(4))
print('bad', len(bad)); [print(x) for x in bad[:12]]
