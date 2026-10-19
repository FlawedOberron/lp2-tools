#!/usr/bin/env python3
"""Replace entries of an ARC v8 archive (in place of the stock data, keeping names, classes and order).

  arcput.py IN.arc OUT.arc NAME.CLASS=FILE [NAME.CLASS=FILE ...]

NAME is matched case-insensitively against the end of each entry name (backslashes), e.g.
  'lp1bg900\\atarionline00.rCollision=atari_bg.rCollision'. Every pair must match at least once.
"""
import os, sys, tempfile, zlib
import arcx


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    puts = []
    for arg in sys.argv[3:]:
        key, path = arg.split("=", 1)
        name, cls = key.rsplit(".", 1)
        puts.append([name.lower(), cls, open(path, "rb").read(), 0])
    d = open(src, "rb").read()
    types = arcx.load_types()
    with tempfile.TemporaryDirectory() as tmp:
        order = []
        for name, th, cs, ds, _fl, off in arcx.entries(d):
            raw = zlib.decompress(d[off:off + cs]) if cs != ds else d[off:off + cs]
            cls = types.get(th, f"0x{th:08x}")
            for p in puts:
                if cls == p[1] and name.lower().endswith(p[0]):
                    raw = p[2]
                    p[3] += 1
            path = os.path.join(tmp, *name.split("\\")) + "." + cls
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(raw)
            order.append(f"{name}\t{cls}\n")
        missing = [f"{p[0]}.{p[1]}" for p in puts if not p[3]]
        if missing:
            raise SystemExit(f"{os.path.basename(src)}: no entry for {', '.join(missing)}")
        open(os.path.join(tmp, ".arcorder"), "w", encoding="latin-1").write("".join(order))
        arcx.pack(tmp, dst)
    print(f"{os.path.basename(src)}: " + ", ".join(f"{p[0].split(chr(92))[-1]} x{p[3]}" for p in puts))


if __name__ == "__main__":
    main()
