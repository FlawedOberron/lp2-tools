#!/usr/bin/env python3
"""Inline an AS2 DoAction's ConstantPool: every Push of a constant (types 8/9) becomes a Push of
the string itself, the ConstantPool action is dropped, and Jump / If offsets and DefineFunction(2)
/ With / Try sizes are recomputed. For scripts injected next to a movie's own DoAction, whose
constant pool Scaleform may resolve them against.

    as2nopool.py IN.bin OUT.bin      (DoAction body, ending in ActionEnd)
"""
import struct
import sys


def parse(code):
    acts, at = [], 0
    while at < len(code):
        op = code[at]
        if op >= 0x80:
            n = struct.unpack_from('<H', code, at + 1)[0]
            acts.append([at, op, bytes(code[at + 3:at + 3 + n])])
            at += 3 + n
        else:
            acts.append([at, op, b''])
            at += 1
    return acts


def cstr(b, at):
    end = b.index(0, at)
    return b[at:end], end + 1


def main():
    code = open(sys.argv[1], 'rb').read()
    acts = parse(code)
    pool = []
    for a in acts:
        if a[1] == 0x88:
            n = struct.unpack_from('<H', a[2], 0)[0]
            at, pool = 2, []
            for _ in range(n):
                s, at = cstr(a[2], at)
                pool.append(s)
    out_acts = []
    for at, op, body in acts:
        if op == 0x88:
            out_acts.append((at, None, b''))  # dropped
            continue
        if op == 0x96:  # Push
            nb, i = bytearray(), 0
            while i < len(body):
                t = body[i]
                if t in (8, 9):
                    idx = body[i + 1] if t == 8 else struct.unpack_from('<H', body, i + 1)[0]
                    nb += b'\x00' + pool[idx] + b'\x00'
                    i += 2 if t == 8 else 3
                    continue
                size = {0: None, 1: 4, 2: 0, 3: 0, 4: 1, 5: 1, 6: 8, 7: 4}[t]
                if size is None:
                    s, j = cstr(body, i + 1)
                    nb += body[i:j]
                    i = j
                else:
                    nb += body[i:i + 1 + size]
                    i += 1 + size
            body = bytes(nb)
        out_acts.append((at, op, body))
    # new layout
    def size(op, body):
        return 0 if op is None else (3 + len(body) if op >= 0x80 else 1)
    newpos, pos = {}, 0
    for at, op, body in out_acts:
        newpos[at] = pos
        pos += size(op, body)
    newpos[len(code)] = pos

    def remap(old):
        if old not in newpos:
            raise SystemExit('branch into the middle of an action at %d' % old)
        return newpos[old]

    old_next = {}
    for k, (at, op, body) in enumerate(out_acts):
        old_next[at] = out_acts[k + 1][0] if k + 1 < len(out_acts) else len(code)
    old_size = {a[0]: (3 + len(a[2]) if a[1] >= 0x80 else 1) for a in acts}
    res = bytearray()
    for at, op, body in out_acts:
        if op is None:
            continue
        b = bytearray(body)
        end_old = at + old_size[at]
        if op in (0x99, 0x9d):  # Jump / If: si16 from the next action
            off = struct.unpack_from('<h', b, 0)[0]
            target = remap(end_old + off)
            struct.pack_into('<h', b, 0, target - (newpos[at] + 3 + len(b)))
        elif op in (0x9b, 0x8e, 0x94):  # DefineFunction / DefineFunction2 / With: trailing u16 size
            n = struct.unpack_from('<H', b, len(b) - 2)[0]
            struct.pack_into('<H', b, len(b) - 2, remap(end_old + n) - (newpos[at] + 3 + len(b)))
        elif op == 0x8f:
            raise SystemExit('Try is not handled')
        res.append(op)
        if op >= 0x80:
            res += struct.pack('<H', len(b)) + b
    open(sys.argv[2], 'wb').write(bytes(res))
    print('%d -> %d bytes, %d constants inlined' % (len(code), len(res), len(pool)))


if __name__ == '__main__':
    main()
