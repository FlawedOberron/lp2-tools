#!/usr/bin/env python3
"""Find strings matching a regex in a PE32 and the data words that point to them."""
import re, struct, sys
data = open(sys.argv[1], 'rb').read(); pat = re.compile(sys.argv[2].encode())
pe = struct.unpack_from('<I', data, 0x3c)[0]
nsec = struct.unpack_from('<H', data, pe+6)[0]; opt = struct.unpack_from('<H', data, pe+20)[0]
base = struct.unpack_from('<I', data, pe+24+28)[0]
secs = []
for i in range(nsec):
    o = pe+24+opt+i*40
    name = data[o:o+8].rstrip(b'\0').decode(); vs, va, rs, ro = struct.unpack_from('<IIII', data, o+8)
    secs.append((name, va, rs, ro))
def off2va(off):
    for n, va, rs, ro in secs:
        if ro <= off < ro+rs: return base+va+off-ro, n
def va2off(v):
    for n, va, rs, ro in secs:
        if base+va <= v < base+va+rs: return v-base-va+ro
strs = {}
for m in re.finditer(rb'[\x20-\x7e]{4,}\0', data):
    s = m.group()[:-1]
    if pat.search(s): strs[off2va(m.start())[0]] = s.decode()
# pointer words to those strings
refs = {}
for i in range(0, len(data)-3, 4):
    w = struct.unpack_from('<I', data, i)[0]
    if w in strs: refs.setdefault(w, []).append(off2va(i))
for v in sorted(strs):
    print(f"{v:#x} {strs[v]!r:40} <- {[(hex(a), s) for a, s in refs.get(v, [])][:6]}")
