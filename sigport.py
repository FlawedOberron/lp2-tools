#!/usr/bin/env python3
"""Find the DX9 address matching a DX11 address by byte signature (analysis only).

    sigport.py <dx11.exe> <dx9.exe> <va> [<va> ...]          code addresses
    sigport.py <dx11.exe> <dx9.exe> data:<site>:<k> ...      the 4-byte absolute at site+k (in code)

A window of DX11 bytes around each address is matched in DX9's .text with rel32 call/jump
operands and any 4-byte value that looks like an address wildcarded; the window grows until the
match is unique. For "data:" the DX9 site is found the same way and the dword at site+k is read.
"""
import re
import struct
import sys


def load(path):
    d = open(path, 'rb').read()
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    n = struct.unpack_from('<H', d, pe + 6)[0]
    opt = struct.unpack_from('<H', d, pe + 20)[0]
    secs = []
    for i in range(n):
        o = pe + 24 + opt + i * 40
        name = d[o:o + 8].rstrip(b'\0')
        vs, va, rs, ro = struct.unpack_from('<IIII', d, o + 8)
        secs.append((name, 0x400000 + va, rs, ro))
    return d, secs


def off(secs, va):
    for _, sva, rs, ro in secs:
        if sva <= va < sva + rs:
            return ro + va - sva
    raise ValueError(hex(va))


def va_of(secs, o):
    for _, sva, rs, ro in secs:
        if ro <= o < ro + rs:
            return sva + o - ro
    return None


def pattern(b, fields=False):
    """Regex for bytes b with relocatable dwords wildcarded (fields: struct offsets 0x100-0x40000 too)."""
    wild = [False] * len(b)
    i = 0
    while i < len(b):
        if b[i] in (0xe8, 0xe9) and i + 5 <= len(b):
            for j in range(i + 1, i + 5):
                wild[j] = True
            i += 5
            continue
        if b[i] == 0x0f and i + 1 < len(b) and 0x80 <= b[i + 1] <= 0x8f and i + 6 <= len(b):
            for j in range(i + 2, i + 6):
                wild[j] = True
            i += 6
            continue
        i += 1
    for i in range(len(b) - 3):
        v = struct.unpack_from('<I', b, i)[0]
        if 0x401000 <= v < 0x1c00000 or (fields and 0x100 <= v < 0x40000):
            for j in range(i, i + 4):
                wild[j] = True
    return b''.join(b'.' if w else re.escape(bytes([c])) for c, w in zip(b, wild))


def port(a, b, va, fields=False):
    da, sa = a
    db, sb = b
    o = off(sa, va)
    text = [s for s in sb if s[0] == b'.text'][0]
    lo, hi = text[3], text[3] + text[2]
    for before, after in ((0, 24), (0, 48), (16, 48), (32, 64), (64, 96), (96, 160)):
        rx = re.compile(pattern(da[o - before:o + after], fields), re.S)
        hits = [m.start() + before for m in rx.finditer(db, lo, hi)]
        if len(hits) == 1:
            return va_of(sb, hits[0]), before + after
        if not hits:
            return None, before + after
    return None, -len(hits)


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    for arg in sys.argv[3:]:
        if arg.startswith('data:'):
            _, site, k = arg.split(':')
            site, k = int(site, 16), int(k, 16)
            v9, w = port(a, b, site)
            if v9 is None:
                print(f'{arg}: no unique match ({w})')
                continue
            v11 = struct.unpack_from('<I', a[0], off(a[1], site) + k)[0]
            d9 = struct.unpack_from('<I', b[0], off(b[1], v9) + k)[0]
            print(f'{arg}: dx11 0x{v11:x} -> dx9 0x{d9:x} (site 0x{v9:x})')
            continue
        va = int(arg, 16)
        v9, w = port(a, b, va)
        if v9 is None:
            v9, w = port(a, b, va, True)
            w = f'{w}, struct offsets wildcarded' if v9 else w
        print(f'0x{va:x} -> ' + (f'0x{v9:x} ({w} bytes)' if v9 else f'none ({w})'))


if __name__ == '__main__':
    main()
