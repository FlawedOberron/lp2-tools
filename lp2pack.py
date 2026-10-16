#!/usr/bin/env python3
"""Build mod packages for the xlive.dll mod loader.

  lp2pack.py map --game GAMEDIR --src 0 --name "Test Arena" [--size medium] OUT.zip

A map package (for the game's Maps folder) holds
  map.json     {"name", "base", "number", "size"?}
  nativePC/... every file of online map <src>, under its own number: the per-area archives,
               shader packages, music, and the per-map resources the game otherwise keeps in boot
               archives (detail\\windows\\*.tde, MaterialSkipList\\*.msl, tool\\scrCollisionArea\\*.swc)
               as loose files.
The DLL gives each package a free online slot (13, 14) and renumbers the files to it, so the same
zip works in either slot. A custom map would replace the archives' contents but keep the names.
"""
import argparse, json, os, sys, tempfile, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapslot  # noqa: E402


def build_map(a):
    native = os.path.join(a.game, "nativePC")
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        entry = {"name": a.name, "base": a.src, "number": a.src}
        if a.size:
            entry["size"] = a.size
        z.writestr("map.json", json.dumps(entry, indent=1))
        for rel in mapslot.map_files(native, a.src):
            s = os.path.join(native, rel)
            if os.path.isdir(s):
                for d, _, fs in os.walk(s):
                    for fn in fs:
                        p = os.path.join(d, fn)
                        z.write(p, "nativePC/" + os.path.relpath(p, native).replace(os.sep, "/"))
            elif os.path.exists(s):
                z.write(s, "nativePC/" + rel)
            else:
                print("missing (skipped):", rel)
        for arc, name, cls, ext in mapslot.BOOT_RESOURCES:
            work = tempfile.mkdtemp(prefix="lp2pack")
            mapslot.extract(os.path.join(native, arc), work)
            res = name.format(a.src)
            z.write(mapslot.path_of(work, res, cls), "nativePC/" + res.replace("\\", "/") + "." + ext)
    with zipfile.ZipFile(a.out) as z:
        print(f"wrote {a.out}: {len(z.namelist())} files, {os.path.getsize(a.out) >> 20} MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="kind", required=True)
    m = sub.add_parser("map")
    m.add_argument("--game", required=True)
    m.add_argument("--src", type=int, required=True)
    m.add_argument("--name", required=True)
    m.add_argument("--size", choices=("small", "medium", "large"))
    m.add_argument("out")
    a = ap.parse_args()
    if a.kind == "map":
        build_map(a)


if __name__ == "__main__":
    main()
