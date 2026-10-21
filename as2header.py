#!/usr/bin/env python3
"""Compile an AS2 script for injection into a game Flash and write it as a C header.

    as2header.py SCRIPT.as BASE.gfx OUT.h ARRAY_NAME

BASE.gfx is the game movie the script will be added to (only used to compile against; nothing of
it ends up in the output). The script is compiled with FFDec as the root frame's DoAction, that
DoAction's body is taken, its ConstantPool inlined (as2nopool.py: Scaleform resolves an added
DoAction's constants against the movie's own pool) and written as `static const uint8_t NAME[]`.
"""
import os
import shutil
import subprocess
import sys
import tempfile

FFDEC = os.path.expanduser('~/Applications/ffdec/ffdec-cli.jar')
HERE = os.path.dirname(os.path.abspath(__file__))


def root_doaction(f):
    at = 8
    nb = f[at] >> 3
    at += (5 + 4 * nb + 7) // 8 + 4
    while at + 2 <= len(f):
        h = f[at] | f[at + 1] << 8
        code, ln, body = h >> 6, h & 0x3f, at + 2
        if ln == 0x3f:
            ln = int.from_bytes(f[body:body + 4], 'little')
            body += 4
        if code == 12:
            return f[body:body + ln]
        if code in (0, 1):
            break
        at = body + ln
    raise SystemExit('no root DoAction in the compiled movie')


def main():
    src, base, out, name = sys.argv[1:5]
    with tempfile.TemporaryDirectory() as tmp:
        scripts = os.path.join(tmp, 'scripts', 'frame_1')
        os.makedirs(scripts)
        shutil.copy(src, os.path.join(scripts, 'DoAction.as'))
        movie = os.path.join(tmp, 'out.gfx')
        r = subprocess.run(['java', '-jar', FFDEC, '-importScript', base, movie, os.path.join(tmp, 'scripts')],
                           capture_output=True, text=True)
        if not os.path.exists(movie):
            raise SystemExit('FFDec failed:\n' + r.stdout + r.stderr)
        raw = os.path.join(tmp, 'raw.bin')
        open(raw, 'wb').write(root_doaction(open(movie, 'rb').read()))
        flat = os.path.join(tmp, 'flat.bin')
        subprocess.run([sys.executable, os.path.join(HERE, 'as2nopool.py'), raw, flat], check=True)
        code = open(flat, 'rb').read()
    lines = [', '.join('0x%02x' % c for c in code[i:i + 16]) for i in range(0, len(code), 16)]
    with open(out, 'w') as h:
        h.write('// Compiled %s (AS2 DoAction bytecode, our code only), made by lp2-tools/as2header.py:\n'
                '// FFDec compiles it against the game movie, the ConstantPool is inlined.\n' % os.path.basename(src))
        h.write('#pragma once\n#include <cstdint>\nstatic const uint8_t %s[] = {\n\t%s\n};\n' % (name, ',\n\t'.join(lines)))
    print('%s: %d bytes' % (out, len(code)))


if __name__ == '__main__':
    main()
