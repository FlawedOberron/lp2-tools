#!/usr/bin/env python3
"""Port a C initializer row of LP2 addresses from a Steam exe to the disc (1.1) exe of the same renderer.

    porttable.py dx11|dx9 va|rva < row.txt

Reads C text on stdin and writes it back with every address ported (retailport.py). Values that aren't addresses
(struct offsets, sizes, flags) are left as they are: in va mode a number is an address when it lies in the exe
image (0x401000..0x1c00000); in rva mode when number + 0x400000 does and the number is at least 0x10000 (smaller
values are taken for offsets; check those by hand). Failures are written as 0 /*??0x...*/ and listed on stderr;
every ported value is listed on stderr as old -> new (kind).
"""
import os
import re
import sys

import retailport
import sigport

HERE = os.path.dirname(os.path.abspath(__file__))
RETAIL = os.path.expanduser('~/Games/lp2-retail/prefix/drive_c/Program Files (x86)/Capcom/Lost Planet 2')
EXES = {
    'dx11': (os.path.join(HERE, 'unpack/LP2DX11.exe.unpacked.exe'), os.path.join(RETAIL, 'LP2DX11.exe')),
    'dx9': (os.path.join(HERE, 'unpack/LP2DX9.exe.unpacked.exe'), os.path.join(RETAIL, 'LP2DX9.exe')),
}
_cache = {}


def exes(which):
    if which not in _cache:
        a, b = EXES[which]
        _cache[which] = (sigport.load(a), sigport.load(b))
    return _cache[which]


def port_va(which, va):
    a, b = exes(which)
    sec = retailport.section_of(a[1], va)
    if sec == '.text':
        return retailport.port_code(a, b, va), 'code'
    v, n, refs = retailport.port_data(a, b, va)
    return v, f'data {n}/{refs}'


def main():
    which, mode = sys.argv[1], sys.argv[2]
    text = sys.stdin.read()

    def sub(m):
        s = m.group(0)
        n = int(s, 16)
        if mode == 'va':
            if not 0x401000 <= n < 0x1c00000:
                return s
            v, kind = port_va(which, n)
            new = v
        else:
            if n < 0x10000 or not 0x401000 <= n + 0x400000 < 0x1c00000:
                return s
            v, kind = port_va(which, n + 0x400000)
            new = v - 0x400000 if v is not None else None
        if new is None:
            print(f'FAIL {s} ({kind})', file=sys.stderr)
            return f'0 /*??{s}*/'
        print(f'{s} -> 0x{new:x} ({kind})', file=sys.stderr)
        return f'0x{new:x}'

    sys.stdout.write(re.sub(r'\b0x[0-9a-fA-F]+\b', sub, text))


if __name__ == '__main__':
    main()
