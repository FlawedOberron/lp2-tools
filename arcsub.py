#!/usr/bin/env python3
"""Same-length byte substitution in an ARC v8 archive: entry names and every entry's data.

  arcsub.py IN.arc OUT.arc REGEX REPLACEMENT [REGEX REPLACEMENT ...]

Patterns are Python bytes regexes (case-insensitive); every match must keep its length (string
tables and fixed fields stay valid). Used to give a ported map its own resource paths, e.g.
  'scr\\\\online\\\\online00\\\\' 'scr\\\\Online\\\\lp1bg900\\\\'
so the engine's path-keyed resource cache cannot hand back the stock map's files.
"""
import os, re, sys, tempfile, zlib
import arcx


def main():
    if len(sys.argv) < 5 or len(sys.argv) % 2 == 0:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    subs = [(re.compile(sys.argv[i].encode(), re.I), sys.argv[i + 1].encode()) for i in range(3, len(sys.argv), 2)]

    def sub(data):
        n = 0
        for rx, rep in subs:
            def f(m):
                exp = m.expand(rep)
                if len(exp) != len(m.group(0)):
                    raise SystemExit(f"length change: {m.group(0)!r} -> {exp!r}")
                return exp
            data, k = rx.subn(f, data)
            n += k
        return data, n

    d = open(src, "rb").read()
    types = arcx.load_types()
    with tempfile.TemporaryDirectory() as tmp:
        order, total = [], 0
        for name, th, cs, ds, _fl, off in arcx.entries(d):
            raw = zlib.decompress(d[off:off + cs]) if cs != ds else d[off:off + cs]
            raw, k = sub(raw)
            nb, k2 = sub(name.encode("latin-1"))
            total += k + k2
            name, cls = nb.decode("latin-1"), types.get(th, f"0x{th:08x}")
            p = os.path.join(tmp, *name.split("\\")) + "." + cls
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(raw)
            order.append(f"{name}\t{cls}\n")
        open(os.path.join(tmp, ".arcorder"), "w", encoding="latin-1").write("".join(order))
        arcx.pack(tmp, dst)
    print(f"{os.path.basename(src)}: {total} substitution(s), {len(order)} entries")


if __name__ == "__main__":
    main()
