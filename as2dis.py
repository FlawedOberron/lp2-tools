#!/usr/bin/env python3
"""Minimal SWF/GFX AS2 disassembler: lists DefineFunction(2) bodies by name (for reading Scaleform UIs).
usage: as2dis.py FILE.gfx [function-name-regex]"""
import re, struct, sys, zlib

NAMES = {0x04:'NextFrame',0x06:'Play',0x07:'Stop',0x0a:'Add',0x0b:'Subtract',0x0c:'Multiply',0x0d:'Divide',
 0x0e:'Equals',0x0f:'Less',0x10:'And',0x11:'Or',0x12:'Not',0x17:'Pop',0x18:'ToInteger',0x1c:'GetVariable',
 0x1d:'SetVariable',0x20:'SetTarget2',0x21:'StringAdd',0x26:'Trace',0x3c:'DefineLocal',0x3d:'CallFunction',
 0x3e:'Return',0x3f:'Modulo',0x40:'NewObject',0x41:'DefineLocal2',0x42:'InitArray',0x43:'InitObject',0x44:'TypeOf',
 0x47:'Add2',0x48:'Less2',0x49:'Equals2',0x4a:'ToNumber',0x4b:'ToString',0x4c:'PushDuplicate',0x4e:'GetMember',
 0x4f:'SetMember',0x50:'Increment',0x51:'Decrement',0x52:'CallMethod',0x53:'NewMethod',0x54:'InstanceOf',
 0x60:'BitAnd',0x61:'BitOr',0x63:'BitLShift',0x66:'StrictEquals',0x67:'Greater',0x81:'GotoFrame',0x83:'GetURL',
 0x87:'StoreRegister',0x88:'ConstantPool',0x8c:'GoToLabel',0x94:'With',0x96:'Push',0x99:'Jump',0x9d:'If',
 0x9e:'Call',0x9f:'GotoFrame2',0x9b:'DefineFunction',0x8e:'DefineFunction2'}

def cstr(b, o):
    e = b.index(b'\0', o)
    return b[o:e].decode('latin1'), e + 1

def actions(b, start, end, pool, depth, want, out, fname=None):
    o = start
    while o < end:
        code = b[o]; o += 1
        length = 0
        if code >= 0x80:
            length = struct.unpack_from('<H', b, o)[0]; o += 2
        body = b[o:o+length]; at = o; o += length
        name = NAMES.get(code, '0x%02x' % code)
        if code == 0x88:
            n = struct.unpack_from('<H', body, 0)[0]; p = 2; pool[:] = []
            for _ in range(n):
                s, p = cstr(body, p); pool.append(s)
            continue
        if code in (0x9b, 0x8e):
            fn, p = cstr(body, 0)
            if code == 0x9b:
                n = struct.unpack_from('<H', body, p)[0]; p += 2
                for _ in range(n): _, p = cstr(body, p)
                size = struct.unpack_from('<H', body, p)[0]
            else:
                n, regs, flags = struct.unpack_from('<HBH', body, p); p += 5
                params = []
                for _ in range(n):
                    r = body[p]; s, p = cstr(body, p + 1); params.append('%s/r%d' % (s, r))
                size = struct.unpack_from('<H', body, p)[0]
            show = want is None or (fn and re.search(want, fn))
            if show:
                out.append('%sfunction %s(%s)' % ('  ' * depth, fn, ','.join(params) if code == 0x8e else ''))
            actions(b, o, o + size, list(pool), depth + 1, None if show else want, out if show else out, fn)
            o += size
            continue
        if want is not None:
            continue
        arg = ''
        if code == 0x96:
            p = 0; vals = []
            while p < len(body):
                t = body[p]; p += 1
                if t == 0: s, p = cstr(body, p); vals.append(repr(s))
                elif t == 1: vals.append('%g' % struct.unpack_from('<f', body, p)[0]); p += 4
                elif t in (2, 3): vals.append('null' if t == 2 else 'undef')
                elif t == 4: vals.append('r%d' % body[p]); p += 1
                elif t == 5: vals.append('true' if body[p] else 'false'); p += 1
                elif t == 6: vals.append('%g' % struct.unpack_from('<d', body[p+4:p+8] + body[p:p+4])[0]); p += 8
                elif t == 7: vals.append(str(struct.unpack_from('<i', body, p)[0])); p += 4
                elif t == 8: i = body[p]; vals.append(repr(pool[i]) if i < len(pool) else '#%d' % i); p += 1
                elif t == 9: i = struct.unpack_from('<H', body, p)[0]; vals.append(repr(pool[i]) if i < len(pool) else '#%d' % i); p += 2
                else: vals.append('?'); break
            arg = ' '.join(vals)
        elif code in (0x99, 0x9d):
            arg = '%+d' % struct.unpack_from('<h', body, 0)[0]
        elif code == 0x87:
            arg = 'r%d' % body[0]
        elif code == 0x8c:
            arg, _ = cstr(body, 0)
        out.append('%s%s %s' % ('  ' * depth, name, arg))

def tags(b, o, end, want, out):
    while o < end:
        h = struct.unpack_from('<H', b, o)[0]; o += 2
        t, l = h >> 6, h & 0x3f
        if l == 0x3f: l = struct.unpack_from('<I', b, o)[0]; o += 4
        if t in (12, 59):
            s = o + (2 if t == 59 else 0)
            actions(b, s, o + l, [], 0, want, out)
        elif t == 39:
            tags(b, o + 4, o + l, want, out)
        o += l

d = open(sys.argv[1], 'rb').read()
if d[:3] == b'CWS': d = d[:8] + zlib.decompress(d[8:])
nbits = d[8] >> 3
o = 8 + (5 + 4 * nbits + 7) // 8 + 4
out = []
tags(d, o, len(d), sys.argv[2] if len(sys.argv) > 2 else None, out)
print('\n'.join(out))
