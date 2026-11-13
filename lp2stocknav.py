#!/usr/bin/env python3
"""Bot zones for LP2's own online maps, embedded in xlive.dll (src/mods/stocknav_data.h).

  lp2stocknav.py --game LP2_DIR --library LIB OUT_HEADER [NN ...]     every stock map in LIB/lp2 (or the ones given)

Per map: lp2project.py import-lp2 (stage, move collision, the stock spawns and pickups as the layout) into a work
folder, then lp2navmap.py (Recast over the move collision, playable area from the markers, zones and links: the same
data a map package carries as map.json "nav_zones"). Online areas have no navmesh of their own (only the training
areas, aArea_TUTOREAL_*, do), so bots route on these in System Link and online matches alike.

Embedded form (little endian, raw deflate; the DLL inflates it with puff):
  u32 zones; per zone: f32 pos[3], f32 size[3], u16 loops, per loop u16 points, points x f32[3]
  u32 links; per link: u16 from, u16 to, u8 kind (0 walk 1 jump 2 drop 3 grapple 4 launch 5 ladder), f32 length, f32 a[3], f32 b[3]
Zone names are z<index> (stock maps have no zone volumes, so no names or tags of their own).
The data is derived from the player's own install (collision outlines), no game files are copied into the DLL.

  --area OUT.bin: the navmesh the game's own bot AI walks on (cAIPlanMoveHmAction needs it loaded by the area), per map:
  the generated rAINavigationMeshList, rAIWayPoint and an empty rIntelligenceBox, and the area's rScrList with entries
  29/30/31 naming them, as COPY / ADD ops against the player's own (lp2brain.delta). The DLL .incbin's it
  (src/mods/stockarea.bin) and adds them to aArea_ONLINE_NN.arc when the game opens it. Little endian:
    'SAR1' u32 maps; per map: u32 map, u32 entries; per entry: u16 n name, u16 n class, u8 kind (0 new, deflated;
    1 ops against the stock entry of that name; 2 copied from the player's own archive named by the n bytes, in the
    same folder), u32 size, u32 crc32 (of the result), u32 n, n bytes
  Stock maps whose stage has a training version (TRAINING) get Capcom's own navmesh, way points and intelligence box,
  copied at load from the player's aArea_TUTOREAL_NN.arc: hand made, with their jump links, where the generated one
  misses connections (Pirate Fortress' levels only joined by grapples).
"""
import argparse, glob, json, os, struct, subprocess, sys, tempfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = {"walk": 0, "jump": 1, "drop": 2, "grapple": 3, "launch": 4, "ladder": 5}


def pack(nz):
    out = [struct.pack("<I", len(nz["zones"]))]
    for i, z in enumerate(nz["zones"]):
        if z.get("name") not in (None, "z%d" % i) or z.get("tags"):
            raise SystemExit(f"zone {i} has a name or tags of its own ({z.get('name')}, {z.get('tags')}): not a stock zone")
        out.append(struct.pack("<6f", *z["pos"], *z["size"]))
        loops = z.get("outline") or []
        out.append(struct.pack("<H", len(loops)))
        for loop in loops:
            out.append(struct.pack("<H", len(loop)))
            out.append(b"".join(struct.pack("<3f", *q) for q in loop))
    out.append(struct.pack("<I", len(nz["links"])))
    for e in nz["links"]:
        out.append(struct.pack("<HHBf6f", e["from"], e["to"], KINDS[e.get("kind", "walk")], float(e.get("length", 0.0)),
                               *e["a"], *e["b"]))
    return b"".join(out)


def build(nn, game, library, work):
    folder = os.path.join(work, "map" + nn)
    subprocess.run([sys.executable, os.path.join(HERE, "lp2project.py"), "import-lp2", nn, folder, "--name", "stock " + nn,
                    "--game", game, "--library", library], check=True, stdout=subprocess.DEVNULL)
    pj = os.path.join(folder, "project.json")
    p = json.load(open(pj))
    p["nav_settings"] = dict(p.get("nav_settings") or {}, weld=STOCK_WELD)
    p["volumes"] = [v for v in p.get("volumes", []) if not v.get("stock_limits")] + [
        {"pos": list(pos), "size": list(size), "yaw": 0.0, "limits": True, "stock_limits": True} for pos, size in STOCK_LIMITS.get(nn, ())]
    json.dump(p, open(pj, "w"), indent=1)
    prev = os.path.join(folder, ".preview")
    os.makedirs(prev, exist_ok=True)
    link = os.path.join(prev, "stage")
    if not os.path.lexists(link):
        os.symlink(os.path.join("..", "assets", "lp2", "stage"), link)   # the stage lp2colview reads (the editor's preview)
    r = subprocess.run([sys.executable, os.path.join(HERE, "lp2navmap.py"), folder, "--library", library],
                       check=True, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(("playable area", "zones:")):
            print(f"  map {nn}: {line}")
    return json.load(open(os.path.join(prev, "navzones.json")))


STOCK_WELD = 60.0   # cm: auto welds (lp2navgen.auto_welds) on stock maps: Recast splits their floors at every step (map 06:
                    # the main piece 944 -> 2019 of 2246 polygons with them; bots stood with no path between pieces)
STOCK_LIMITS = {   # map limits volumes (floor centre, size; cm) the bots' navmesh is cut to, marked out by the user 2026-11-13
    "07": [((-21525, -3230, 2788), (19210, 8510, 28150))],   # NEOS: low gravity + jump packs; the rest (ships) bots can't do
    "15": [((-120, 389 - 3435, 15855), (26910, 6870, 33030))],   # Frozen Wasteland: the central crater (the y given, 389,
}                                                             # is the box's middle: as the floor it cut half the crater)
TRAINING = {"01": "41", "09": "46", "10": "31", "12": "26"}   # online map -> training area on the same stage (navmesh extents)


def area(nn, game, work):
    import lp2mapc, lp2nav, lp2brain, numpy as np
    folder = os.path.join(work, "map" + nn)
    tag = ("lp2o" + nn).ljust(8, "_")
    names = {29: f"tool\\AI\\NaviMesh\\{tag}\\List_{tag}", 30: f"tool\\AI\\NaviMesh\\{tag}\\Way_{tag}", 31: f"tool\\AI\\AreaAI\\{tag}"}
    nav = os.path.join(folder, "assets", "nav")
    with open(os.path.join(folder, ".preview", "navmesh.bin"), "rb") as f:
        n = struct.unpack("<I", f.read(4))[0]
        tri = np.frombuffer(f.read(n * 36), "<f4").reshape(-1, 3)
    box = lp2nav.empty_intelligence_box((float(tri[:, 0].min()), float(tri[:, 2].min())), (float(tri[:, 0].max()), float(tri[:, 2].max())))
    out = []
    arcs = os.path.join(game, "nativePC", "arcXmlTmpPC")
    if nn in TRAINING:
        src = f"aArea_TUTOREAL_{TRAINING[nn]}.arc"
        e = lp2mapc.entries(os.path.join(arcs, src))
        names = {}
        for kind, cls in ((29, "rAINavigationMeshList"), (30, "rAIWayPoint"), (31, "rIntelligenceBox")):
            nm, raw = e[cls][0]
            names[kind] = nm
            out.append((nm, cls, 2, raw, src.encode()))
        print(f"  map {nn}: Capcom's navmesh from {src} ({names[29]})")
        for nm, b in lp2mapc.entries(os.path.join(arcs, f"aArea_ONLINE_{nn}.arc")).get("rScrList", []):
            patched = lp2nav.scrlist_add(b, sorted(names.items()))
            out.append((nm, "rScrList", 1, patched, lp2brain.delta(b, patched)))
        rec = [struct.pack("<II", int(nn), len(out))]
        for name, cls, kind, raw, data in out:
            rec.append(struct.pack("<H", len(name)) + name.encode("latin-1") + struct.pack("<H", len(cls)) + cls.encode()
                       + struct.pack("<BIII", kind, len(raw), zlib.crc32(raw), len(data)) + data)
        return b"".join(rec)
    def new(name, cls, raw):
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        out.append((name, cls, 0, raw, c.compress(raw) + c.flush()))
    lnv = os.path.join(nav, f"List_{tag}.rAINavigationMeshList")
    meshes = lp2nav.load(lnv)[1]
    if not any(len(set(p["tri"]) & set(meshes[0]["polys"][l[0]]["tri"])) < 2 for p in meshes[0]["polys"] for l in p["links"]):
        import lp2navgen   # made before cross links existed (--reuse): add them now
        nz = json.load(open(os.path.join(folder, ".preview", "navzones.json")))
        lp2navgen.cross_links(meshes[0], nz["links"], lambda t: print(f"  map {nn}: {t}"))
        open(lnv, "wb").write(lp2nav.write_lnv(meshes))
    new(names[29], "rAINavigationMeshList", open(lnv, "rb").read())
    new(names[30], "rAIWayPoint", open(os.path.join(nav, f"Way_{tag}.rAIWayPoint"), "rb").read())
    new(names[31], "rIntelligenceBox", box)
    arc = os.path.join(game, "nativePC", "arcXmlTmpPC", f"aArea_ONLINE_{nn}.arc")
    for nm, b in lp2mapc.entries(arc).get("rScrList", []):
        patched = lp2nav.scrlist_add(b, sorted(names.items()))
        out.append((nm, "rScrList", 1, patched, lp2brain.delta(b, patched)))
    rec = [struct.pack("<II", int(nn), len(out))]
    for name, cls, kind, raw, data in out:
        rec.append(struct.pack("<H", len(name)) + name.encode("latin-1") + struct.pack("<H", len(cls)) + cls.encode()
                   + struct.pack("<BIII", kind, len(raw), zlib.crc32(raw), len(data)) + data)
    return b"".join(rec)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--library", required=True)
    ap.add_argument("--work", help="work folder (default: a temporary one)")
    ap.add_argument("--area", help="also write the navmesh blob (src/mods/stockarea.bin)")
    ap.add_argument("--reuse", action="store_true", help="use the work folder's maps as they are (no rebuild)")
    ap.add_argument("--rebuild", default="", help="with --reuse: these maps (comma list, e.g. 07,15) are rebuilt anyway")
    ap.add_argument("out")
    ap.add_argument("maps", nargs="*")
    a = ap.parse_args()
    maps = a.maps or sorted(os.path.basename(d)[3:] for d in glob.glob(os.path.join(a.library, "lp2", "map[0-9][0-9]")))
    maps = ["%02d" % int(m) for m in maps]
    tmp = None if a.work else tempfile.TemporaryDirectory()
    work = a.work or tmp.name
    os.makedirs(work, exist_ok=True)
    rows, total = [], 0
    redo = {"%02d" % int(m) for m in a.rebuild.split(",") if m.strip()}
    for nn in maps:
        nzp = os.path.join(work, "map" + nn, ".preview", "navzones.json")
        reuse = a.reuse and nn not in redo and os.path.exists(nzp)
        raw = pack(json.load(open(nzp)) if reuse else build(nn, a.game, a.library, work))
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        z = c.compress(raw) + c.flush()
        total += len(z)
        rows.append((int(nn), len(raw), z))
        print(f"  map {nn}: {len(raw)} bytes -> {len(z)} deflated")
    with open(a.out, "w") as f:
        f.write("// Generated by lp2-tools/lp2stocknav.py from the stock maps' collision: bot zones per online map.\n")
        f.write("// Format: lp2stocknav.py docstring. Don't edit by hand.\n#pragma once\n#include <stdint.h>\n\n")
        for n, size, z in rows:
            f.write(f"static const uint8_t kStockNav{n:02d}[] = {{")
            for i, b in enumerate(z):
                f.write(("\n\t" if i % 24 == 0 else "") + f"{b},")
            f.write("\n};\n")
        f.write("\nstruct StockNavBlob {\n\tint map;\n\tuint32_t size; // inflated\n\tconst uint8_t* data;\n\tuint32_t packed;\n};\n")
        f.write("static const StockNavBlob kStockNav[] = {\n")
        for n, size, z in rows:
            f.write(f"\t{{{n}, {size}u, kStockNav{n:02d}, {len(z)}u}},\n")
        f.write("};\n")
    print(f"{len(rows)} map(s), {total} bytes deflated -> {a.out}")
    if a.area:
        blobs = [area(nn, a.game, work) for nn in maps]
        open(a.area, "wb").write(b"SAR1" + struct.pack("<I", len(blobs)) + b"".join(blobs))
        print(f"navmesh blob: {len(blobs)} map(s), {os.path.getsize(a.area)} bytes -> {a.area}")
    if tmp:
        tmp.cleanup()


if __name__ == "__main__":
    main()
