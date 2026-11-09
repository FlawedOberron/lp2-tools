#!/usr/bin/env python3
"""Frozen Wasteland (Jeeps): LP2's stock online map 15, unchanged stage, as a map package whose every layout's
ground VS spawns are jeeps (VS type 0x16, which lp2jeepmodel.py dresses as the jeep), plus the jeep driver's
ground (nativePC/jeep/aArea_ONLINE_15.col, renumbered to the slot with the rest; jeep_drive.cpp loads it).

  lp2jeepmap.py GAME_DIR [--out GAME_DIR/Maps/FrozenWastelandJeeps.zip] [--base 15] [--name ...]

Stock files from the user's own install (nothing shipped): aArea_ONLINE_15 archives (the object sets in _v.arc
patched), its stage packages (DX9 + DX11) and music. Fixed turrets (type family 03 / 29 / 53 / 79 / 99 / a9),
akrid and gimmicks in the VS group stay as they are; every other VS record becomes a jeep with vs16's stock mounts.
map.json preloads uVs16 (the base map doesn't have it)."""
import argparse
import glob
import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2jeepcol  # noqa: E402
import lp2pack  # noqa: E402
import lp2layout  # noqa: E402
import objset  # noqa: E402

JEEP = 0x16
TURRETS = {0x03, 0x29, 0x53, 0x79, 0x99, 0xA9}


def patch(b):
    """an rObjSet: VS records -> jeeps; returns (bytes, changed, kept types)"""
    b = bytearray(b)
    counts = struct.unpack_from("<4H", b, 0x0A)
    changed, kept = 0, set()
    off = 0x30
    for _ in range(counts[0]):
        t = struct.unpack_from("<H", b, off + 0x1A)[0]
        if "%02x" % t in lp2layout.VS_TYPES and t not in TURRETS:
            rec = bytearray(b[off:off + objset.SIZES[1]])
            struct.pack_into("<H", rec, 0x1A, JEEP)
            lp2layout.put_weapons(rec, {})
            b[off:off + objset.SIZES[1]] = rec
            changed += 1
        else:
            kept.add("%02x" % t)
        off += objset.SIZES[1]
    return bytes(b), changed, kept


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game")
    ap.add_argument("--base", type=int, default=15)
    ap.add_argument("--name", default="Frozen Wasteland (Jeeps)")
    ap.add_argument("--size", default="large")
    ap.add_argument("--out")
    a = ap.parse_args()
    nn = "%02d" % a.base
    out = a.out or os.path.join(a.game, "Maps", "FrozenWastelandJeeps.zip")
    nat = os.path.join(a.game, "nativePC")
    v_arc = os.path.join(nat, "arcXmlTmpPC", "variable", f"aArea_ONLINE_{nn}_v.arc")
    if not os.path.exists(v_arc):
        sys.exit(f"no {v_arc}")
    with tempfile.TemporaryDirectory() as tmp:
        ex = os.path.join(tmp, "v")
        subprocess.run([sys.executable, os.path.join(HERE, "arcx.py"), "x", v_arc, ex], check=True, stdout=subprocess.DEVNULL)
        total, kept = 0, set()
        for f in sorted(glob.glob(os.path.join(ex, "**", "*.rObjSet"), recursive=True)):
            nb, n, k = patch(open(f, "rb").read())
            open(f, "wb").write(nb)
            total += n
            kept |= k
            print(f"  {os.path.basename(f)}: {n} jeep(s)")
        new_v = os.path.join(tmp, "v.arc")
        subprocess.run([sys.executable, os.path.join(HERE, "arcx.py"), "pack", ex, new_v], check=True, stdout=subprocess.DEVNULL)
        # the jeep's ground: the map's move collision (same as Mods\jeep\onlineNN.col)
        col = os.path.join(tmp, "ground.col")
        sbc = os.path.expanduser(f"~/Projects/lp2-assets/library/lp2/map{nn}/assets/move.sbc1")
        if not os.path.exists(sbc):
            sys.exit(f"no {sbc}: run lp2stockmaps.py for map {nn} first")
        ntri = lp2jeepcol.convert(sbc, col)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # the stock map as lp2pack.py packs one (its archives, stage packages, music and the per-map resources from
        # the boot archives: detail .tde, .msl, .swc), then our object sets, ground and preload on top
        stock = os.path.join(tmp, "stock.zip")
        lp2pack.build_map(argparse.Namespace(game=a.game, src=a.base, name=a.name, size=a.size, out=stock))
        v_rel = f"nativePC/arcXmlTmpPC/variable/aArea_ONLINE_{nn}_v.arc"
        tmp_zip = out + ".tmp"
        with zipfile.ZipFile(stock) as src, zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            names = src.namelist()
            if v_rel not in names:
                sys.exit(f"lp2pack's package has no {v_rel}")
            for n in names:
                if n == "map.json":
                    z.writestr(n, json.dumps({"name": a.name, "base": a.base, "number": a.base, "size": a.size,
                                              "preload": ["uVs16"]}, indent=1))
                elif n == v_rel:
                    z.write(new_v, n)
                else:
                    z.writestr(src.getinfo(n), src.read(n))
            z.write(col, f"nativePC/jeep/aArea_ONLINE_{nn}.col")
            count = len(names) + 1
        os.replace(tmp_zip, out)
    print(f"{total} jeep spawns over the layouts (other VS-group types kept: {' '.join(sorted(kept)) or 'none'}), "
          f"ground {ntri} triangles, {count} files -> {out}")


if __name__ == "__main__":
    main()
