#!/usr/bin/env python3
"""Lost Planet 2 DLC descriptor  <package>\\Content\\NativePC\\sname.bin  (read / write).

  snamebin.py FILE                 dump as JSON
  snamebin.py --build IN.json OUT  write sname.bin from JSON (same shape as the dump)

Reconstructed from the parser at FUN_00855140 (LP2DX9.exe 0x855140); nothing here has been
checked against a real Capcom package yet.

  bytes 0-2   ignored (probably a UTF-8 BOM)
  "NN\\r\\n"  entry count, two ASCII decimal digits
  entries, every value on its own CRLF line, numbers as two decimal digits:
    map:   "00", area id            only 04 / 08 / 11 / 15 are accepted (ONLINE_04/08/11/15)
    part:  category 1-4 (1 head hd, 2 body bd, 3 back bk, 4 legs lg), item 00-69,
           7 display-name lines (language slots, see LANGS; each 1-43 bytes, must not be empty),
           then floats, one per line:
             head: 3 (one vec3)        body: 3 (one vec3)
             back: 12 (four vec3)      legs: none
  The game reads only the first 1024 bytes.

A part entry (category c, item n) makes the game load part id 180+n of category c from
  arcXmlTmpPC\\CustomParts\\<hd|bd|bk|lg>2e<nn>.arc and <..>2e<nn><colour>.arc
inside this package's Content folder. The descriptor's variant byte selects nn; the descriptor
tables in the exe put n < 45 at variant n.
"""
import json, sys

CATS = {1: "head", 2: "body", 3: "back", 4: "legs"}
FLOATS = {1: 3, 2: 3, 3: 12, 4: 0}
MAPS = (4, 8, 11, 15)
# name slot -> game language code (FUN_00855df0); 1 is also the fallback
LANGS = {0: 2, 1: 1, 2: 4, 3: 3, 4: 6, 5: 5, 6: 7}
LIMIT = 1024


def parse(b):
    lines = b[3:].split(b"\r\n")
    it = iter(lines)
    nxt = lambda: next(it).decode("utf-8")
    count = int(nxt())
    out = []
    for _ in range(count):
        cat = int(nxt())
        if cat == 0:
            out.append({"map": int(nxt())})
            continue
        e = {"category": CATS[cat], "item": int(nxt()), "names": [nxt() for _ in range(7)]}
        e["floats"] = [float(nxt()) for _ in range(FLOATS[cat])]
        out.append(e)
    return out


def build(entries):
    rev = {v: k for k, v in CATS.items()}
    lines = [f"{len(entries):02d}"]
    for e in entries:
        if "map" in e:
            if e["map"] not in MAPS:
                raise ValueError(f"map {e['map']}: the game only accepts {MAPS}")
            lines += ["00", f"{e['map']:02d}"]
            continue
        cat = rev[e["category"]]
        if not 0 <= e["item"] < 70:
            raise ValueError("item must be 0-69")
        names = e["names"]
        if len(names) != 7 or any(not n or len(n.encode()) > 43 for n in names):
            raise ValueError("need 7 non-empty names of at most 43 bytes")
        fl = e.get("floats", [0.0] * FLOATS[cat])
        if len(fl) != FLOATS[cat]:
            raise ValueError(f"{e['category']} needs {FLOATS[cat]} floats")
        lines += [f"{cat:02d}", f"{e['item']:02d}", *names, *(f"{v:g}" for v in fl)]
    data = b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8")
    if len(data) > LIMIT:
        raise ValueError(f"{len(data)} bytes; the game reads only {LIMIT}. Split into more packages.")
    return data


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--build":
        data = build(json.load(open(a[1])))
        open(a[2], "wb").write(data)
        print(f"wrote {a[2]} ({len(data)} bytes)")
    elif a:
        print(json.dumps(parse(open(a[0], "rb").read()), indent=1, ensure_ascii=False))
    else:
        raise SystemExit(__doc__)
