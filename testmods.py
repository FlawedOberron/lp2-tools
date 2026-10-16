#!/usr/bin/env python3
"""Build the two overlay test mods into GAME/mods/ (enabled from xlive_steamworks.json "mods").

  testmods.py GAME_DIR

  test_part  set 28 variant 00 (hd/bd/bk/lg 2800) recoloured magenta: replaces the stock part
  test_map   aArea_ONLINE_00.arc with every TeamBattle / KojinBattle spawn raised 30 m
"""
import os, shutil, struct, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx, dlcpart, xfs  # noqa: E402

LIFT_CM = 3000.0


def magenta_565(c):
    r, g, b = (c >> 11) / 31, ((c >> 5) & 63) / 63, (c & 31) / 31
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    hi, lo = min(1.0, 0.35 + lum * 2.0), min(1.0, lum * 0.4)
    return (round(hi * 31) << 11) | (round(lo * 63) << 5) | round(hi * 31)


def part_mod(native, out):
    dlcpart.TINTS["magenta"] = magenta_565
    src = os.path.join(native, "arcXmlTmpPC", "CustomParts")
    dst = os.path.join(out, "nativePC", "arcXmlTmpPC", "CustomParts")
    os.makedirs(dst, exist_ok=True)
    for pfx in ("hd", "bd", "bk", "lg"):
        for suffix in ("", "00", "01", "02", "03"):
            name = f"{pfx}2800{suffix}.arc"
            if os.path.exists(os.path.join(src, name)):
                n = dlcpart.clone_arc(os.path.join(src, name), os.path.join(dst, name), [], "magenta")
                print(f"test_part: {name} ({n} entries)")


def map_mod(native, out):
    arc = os.path.join(native, "arcXmlTmpPC", "aArea_ONLINE_00.arc")
    work = tempfile.mkdtemp(prefix="lp2map")
    try:
        sys.argv = ["arcx", "x", arc, work]
        arcx.main()
        lifted = 0
        for root, _, files in os.walk(work):
            for f in files:
                if f.endswith(".rInitPosSet") and ("TeamBattle" in f or "KojinBattle" in f):
                    p = os.path.join(root, f)
                    b = bytearray(open(p, "rb").read())
                    offs = []
                    xfs.parse(bytes(b), offs)
                    for name, o in offs:
                        if name == "Pos":
                            y = struct.unpack_from("<f", b, o + 4)[0]
                            struct.pack_into("<f", b, o + 4, y + LIFT_CM)
                            lifted += 1
                    open(p, "wb").write(b)
        dst = os.path.join(out, "nativePC", "arcXmlTmpPC")
        os.makedirs(dst, exist_ok=True)
        n = arcx.pack(work, os.path.join(dst, "aArea_ONLINE_00.arc"))
        print(f"test_map: aArea_ONLINE_00.arc ({n} entries, {lifted} spawns raised {LIFT_CM / 100:.0f} m)")
    finally:
        shutil.rmtree(work)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    game = sys.argv[1]
    native = os.path.join(game, "nativePC")
    mods = os.path.join(game, "mods")
    for name, build in (("test_part", part_mod), ("test_map", map_mod)):
        out = os.path.join(mods, name)
        shutil.rmtree(out, ignore_errors=True)
        build(native, out)


if __name__ == "__main__":
    main()
