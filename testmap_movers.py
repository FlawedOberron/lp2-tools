#!/usr/bin/env python3
"""Build the "Mover Lab" test package: stock Friction (online 09) plus gimmicks from other maps and ObjSet parenting.

  testmap_movers.py --game GAMEDIR OUT.zip

Added to both -Common rObjSets (main and _v arcs), group 3, after Friction's 35 records (serials 35..):
  35  windmill om835a (Desecration's record), scale 0.01 (~4.5 m), hub 3 m above the crusher corridor floor
  36-39  drums om860e (online 10's record) in a row on the corridor floor, near crusher 25 (it may crush them)
  40  om8322 -> crusher 24 j0, pos LOCAL (0, 650, 0)
  41  om8322 -> crusher 25 j0, pos WORLD (crusher + 650 up)
  42  drum   -> crusher 26 j0, pos WORLD (crusher + 650 up): Havok prop under a parent
  43  om8322 -> windmill j0, pos LOCAL (0, 20000, 0) (blade tip in model units; x0.01 = 2 m if scale carries)
Parent fields (decoded from the DX9 spawner FUN_00f716c0): u8 +0x20 on, u16 +0x24 parent group, u32 +0x28 parent
serial, u32 +0x2C joint. map.json "preload" adds uOm835a and uOm860e (Friction's own list has neither).
The spawn lists after the records are rebuilt (objset.reindex): the game spawns only listed records.
"""
import argparse, json, os, shutil, struct, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2mapc, objset

FLOOR = 1323.0  # crusher corridor (z ~ -200, x -12014 .. -9268)


def record(arc, name_end, serial):
    b = [d for n, d in lp2mapc.entries(arc)["rObjSet"] if n.endswith(name_end)][0]
    counts, _, _ = objset.parse(b)
    off = 0x30 + counts[1] * 0x140 + counts[2] * 0x120
    for i in range(counts[3]):
        r = b[off + i * 0x120:off + (i + 1) * 0x120]
        if struct.unpack_from("<I", r, 0x110)[0] == serial:
            return bytearray(r)
    raise SystemExit(f"{arc}: {name_end} has no group 3 serial {serial}")


def drum_record(arc):
    for n, b in lp2mapc.entries(arc)["rObjSet"]:
        counts, _, _ = objset.parse(b)
        off = 0x30 + counts[1] * 0x140 + counts[2] * 0x120
        for i in range(counts[3]):
            r = b[off + i * 0x120:off + (i + 1) * 0x120]
            if struct.unpack_from("<H", r, 0x1A)[0] == 0x0E86:
                return bytearray(r)
    raise SystemExit(f"{arc}: no om860e drum record")


def place(tpl, serial, pos, scale=None, parent=None, joint=0):
    r = bytearray(tpl)
    struct.pack_into("<I", r, 0x00, 3)
    struct.pack_into("<3f", r, 0x40, *pos)
    if scale is not None:
        struct.pack_into("<3f", r, 0x60, scale, scale, scale)
    if parent is None:
        r[0x20] = 0
        struct.pack_into("<HHIi", r, 0x24, 0, 0, 0, -1)
    else:
        r[0x20] = 1
        struct.pack_into("<HHIi", r, 0x24, 3, 0, parent, joint)
    struct.pack_into("<I", r, 0x110, serial)
    return bytes(r)


def patch(b, recs):
    counts, _, end = objset.parse(b)
    at = 0x30 + counts[1] * 0x140 + counts[2] * 0x120 + counts[3] * 0x120
    assert counts[3] == 35 and counts[4] == 0, counts
    out = bytearray(b[:at]) + b"".join(recs) + b[at:]
    struct.pack_into("<H", out, 0x0E, counts[3] + len(recs))
    return objset.reindex(bytes(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("out")
    a = ap.parse_args()
    X = os.path.join(a.game, "nativePC", "arcXmlTmpPC")
    mill = record(os.path.join(X, "aArea_ONLINE_00.arc"), "-Common", 11)
    drum = drum_record(os.path.join(X, "aArea_ONLINE_10.arc"))
    post = record(os.path.join(X, "aArea_ONLINE_09.arc"), "-Common", 20)  # om8322
    hub = (-10640.0, FLOOR + 300, -200.0)
    recs = [place(mill, 35, hub, scale=0.01)]
    recs += [place(drum, 36 + i, (-11300.0 - 150 * i, FLOOR, -200.0)) for i in range(4)]
    recs += [place(post, 40, (0.0, 650.0, 0.0), parent=24),
             place(post, 41, (-12014.0, 1322.0 + 650, -193.0), parent=25),
             place(drum, 42, (-10067.0, 1276.0 + 650, -10359.0), parent=26),
             place(post, 43, (0.0, 20000.0, 0.0), parent=35)]

    work = tempfile.mkdtemp()
    try:
        pkg = os.path.join(work, "pkg")
        lp2mapc.stock_package(a.game, pkg, 9)
        json.dump({"name": "Mover Lab", "base": 9, "number": 9}, open(os.path.join(pkg, "map.json"), "w"))
        for rel in ("nativePC/arcXmlTmpPC/aArea_ONLINE_09.arc", "nativePC/arcXmlTmpPC/variable/aArea_ONLINE_09_v.arc"):
            arc = os.path.join(pkg, rel)
            name, b = [(n, d) for n, d in lp2mapc.entries(arc)["rObjSet"] if n.endswith("-Common")][0]
            f = os.path.join(work, "common.osf")
            open(f, "wb").write(patch(b, recs))
            lp2mapc.put(arc, {name.split("\\")[-1] + ".rObjSet": f})
        m = json.load(open(os.path.join(pkg, "map.json")))
        m["preload"] = ["uOm835a", "uOm860e"]
        json.dump(m, open(os.path.join(pkg, "map.json"), "w"), indent=1)
        with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(os.path.join(pkg, "map.json"), "map.json")
            for root, _, files in os.walk(pkg):
                for fn in files:
                    p = os.path.join(root, fn)
                    rel = os.path.relpath(p, pkg)
                    if rel != "map.json":
                        z.write(p, rel)
        print(f"{a.out}: {len(recs)} records added")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
