#!/usr/bin/env python3
"""Index every .arc under nativePC -> TSV: arc, class, size, name."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arcx import entries, load_types
root = sys.argv[1]; types = load_types()
for d, _, fs in os.walk(root):
    for f in fs:
        if not f.lower().endswith(".arc"): continue
        p = os.path.join(d, f)
        try:
            data = open(p, "rb").read()
            for name, th, cs, ds, fl, off in entries(data):
                print(f"{os.path.relpath(p, root)}\t{types.get(th, hex(th))}\t{ds}\t{name}")
        except SystemExit as e:
            print(f"{os.path.relpath(p, root)}\tERROR\t0\t{e}", file=sys.stderr)
