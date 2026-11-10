#!/usr/bin/env python3
"""Port addresses from a Steam LP2 exe to the disc (retail 1.1) build of the same renderer (analysis only).

    retailport.py <steam.exe> <retail.exe> <va> [<va> ...]

Code addresses (in .text) are matched by byte signature (sigport.port). Data addresses (globals, tables, strings)
are found through the code that references them: each referencing instruction in the Steam exe is matched in the
retail exe and the operand read there; the answer is the value most references agree on (refs agreeing/total).
Steam exes must be the unpacked ones (lp2-tools/unpack).
"""
import collections
import re
import struct
import sys

import sigport


def section_of(secs, va):
    for name, sva, rs, _ in secs:
        if sva <= va < sva + rs:
            return name.decode()
    return None


def port_window(a, b, va, windows, fields=False):
    """Like sigport.port, but every window is tried (a window with no match doesn't end the search)."""
    da, sa = a
    db, sb = b
    o = sigport.off(sa, va)
    text = [s for s in sb if s[0] == b'.text'][0]
    lo, hi = text[3], text[3] + text[2]
    for before, after in windows:
        rx = re.compile(sigport.pattern(da[o - before:o + after], fields), re.S)
        hits = [m.start() + before for m in rx.finditer(db, lo, hi)]
        if len(hits) == 1:
            return sigport.va_of(sb, hits[0])
    return None


# windows (bytes before, bytes after the address): after it first, then ending at it, then around it
WINDOWS = ((0, 24), (0, 48), (16, 48), (32, 64), (24, 0), (48, 0), (32, 8), (64, 0), (16, 16), (96, 0), (8, 8),
           (12, 12), (64, 32), (96, 160))


def port_code(a, b, va):
    v, w = sigport.port(a, b, va)
    if v is None:
        v, w = sigport.port(a, b, va, True)
    if v is None:
        v = port_window(a, b, va, WINDOWS)
    if v is None:
        v = port_window(a, b, va, WINDOWS, True)
    return v


def port_data(a, b, va, limit=8):
    da, sa = a
    text = [s for s in sa if s[0] == b'.text'][0]
    lo, hi = text[3], text[3] + text[2]
    needle = struct.pack('<I', va)
    votes = collections.Counter()
    refs = 0
    i = da.find(needle, lo, hi)
    while i >= 0 and refs < limit:
        site = sigport.va_of(sa, i)
        v, _ = sigport.port(a, b, site)
        if v is None:
            v = port_window(a, b, site, WINDOWS)
        if v is not None:
            votes[struct.unpack_from('<I', b[0], sigport.off(b[1], v))[0]] += 1
        refs += 1
        i = da.find(needle, i + 1, hi)
    if not votes:
        return None, 0, refs
    value, n = votes.most_common(1)[0]
    return value, n, refs


def main():
    a, b = sigport.load(sys.argv[1]), sigport.load(sys.argv[2])
    for arg in sys.argv[3:]:
        va = int(arg, 16)
        sec = section_of(a[1], va)
        if sec == '.text':
            v = port_code(a, b, va)
            print(f'0x{va:x} code -> ' + (f'0x{v:x}' if v else 'none'))
        elif sec:
            v, n, refs = port_data(a, b, va)
            print(f'0x{va:x} {sec} -> ' + (f'0x{v:x} ({n}/{refs} refs)' if v is not None else f'none (0/{refs} refs)'))
        else:
            # .bss / uninitialised data lies past the file's sections: references still find it
            v, n, refs = port_data(a, b, va)
            print(f'0x{va:x} bss -> ' + (f'0x{v:x} ({n}/{refs} refs)' if v is not None else f'none (0/{refs} refs)'))


if __name__ == '__main__':
    main()
