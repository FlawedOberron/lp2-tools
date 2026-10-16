#!/usr/bin/env python3
"""Build a Lost Planet 2 DLC content package that adds one custom part, by cloning an existing part.

  dlcpart.py --game NATIVEPC --src hd2800 --item 0 --name "Test Helmet" [--tint swap_rb] OUTPKG

  --src    base part(s) to clone, comma separated: <hd|bd|bk|lg><set><variant>, e.g.
           hd2800,bd2800,bk2800,lg2800. The game shows DLC parts as whole outfit sets
           (Sets menu id 0x5d+item; picking it applies the slot to all four categories),
           so a usable DLC item normally provides all four.
  --item   DLC slot 0-69 (game id 180+item). Slots 0-19 show only as whole Sets (Sets menu);
           slots 20-69 also show one by one in each category's part list (the game's own
           menu lists include ids 200-249). Slots 45-69 are flagged Femmes Fatales (faction 4)
           in the game's table, though the menu currently shows DLC parts to every faction.
  Per-part overrides: --src hd2800@20=Green Helmet,hd2900@45=FF Head  (src[@item][=name])
  --tint   swap_rb (subtle) or highlight (bright green) recolours the clone's colour textures
  --colours how many colour arcs to copy (default: every <src>NN.arc that exists, 00-03)

Writes OUTPKG/Content/nativePC/sname.bin and OUTPKG/Content/nativePC/arcXmlTmpPC/CustomParts/*.arc.
The set byte the game puts into DLC part paths is 0x0e, or 0x2e when a caller ORs in 0x20 (normal
parts are 2x, the 'none' part is 0f); until that is pinned down the part is written under both.
"""
import argparse, os, shutil, struct, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx, snamebin, tex2dds  # noqa: E402

CAT = {"hd": "head", "bd": "body", "bk": "back", "lg": "legs"}
DXT5 = (23, 31, 32, 42)
DXT1 = (19, 25)


def swap_rb_565(c):
    return ((c & 0x1F) << 11) | (c & 0x07E0) | (c >> 11)


def highlight_565(c):
    """Luminance mapped to bright green, so the clone is unmistakable in game."""
    r, g, b = (c >> 11) / 31, ((c >> 5) & 63) / 63, (c & 31) / 31
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    g2, rb = min(1.0, 0.35 + lum * 2.0), min(1.0, lum * 0.5)
    return (round(rb * 31) << 11) | (round(g2 * 63) << 5) | round(rb * 31)


TINTS = {"swap_rb": swap_rb_565, "highlight": highlight_565}


def tint_texture(b, tint="swap_rb"):
    """Recolour every DXT colour endpoint (all mips) with TINTS[tint]. BC3 colour blocks are always
    4-colour, so order does not matter there; for BC1 keep c0 > c1 / c0 <= c1 by swapping the
    endpoints and remapping indices when the swap flips their order."""
    t = tex2dds.parse(b)
    if t["fmt"] not in DXT5 + DXT1:
        return b
    out = bytearray(b)
    start = len(b) - len(t["data"])
    step, coff = (16, 8) if t["fmt"] in DXT5 else (8, 0)
    for o in range(start, len(b) - step + 1, step):
        p = o + coff
        c0, c1, idx = struct.unpack_from("<HHI", out, p)
        f = TINTS[tint]
        n0, n1 = f(c0), f(c1)
        if t["fmt"] in DXT1 and (c0 > c1) != (n0 > n1):
            n0, n1 = n1, n0
            if c0 > c1:  # 4-colour: 0<->1, 2<->3
                idx ^= 0x55555555
            else:  # 3-colour: 0<->1, 2 and 3 stay
                idx = sum(((v ^ 1) if v < 2 else v) << (2 * k)
                          for k, v in ((k, (idx >> (2 * k)) & 3) for k in range(16)))
        struct.pack_into("<HHI", out, p, n0, n1, idx)
    return bytes(out)


def rename_pairs(pfx, sset, var, dset, dvar):
    """Same-length renames from a base part to DLC item dvar.

    The game (FUN_00f664b0 in DX11) looks DLC models up under a remapped name:
      model\\hm\\hmf6\\<pfx>f6<vv>\\<pfx>f6<vv>   (+ _BM-00_A, always colour A)
    while effect providers keep the plain set name (effect\\prov\\hm\\hm<set>\\<pfx><set><vv>).
    DLC sounds want hm_2e00\\HEAD_<vv>\\..., which is longer than HEAD_A, so sounds keep
    their original names for now (the part is silent)."""
    s, d = f"{sset:02x}", f"{dset:02x}"
    sv, dv = f"{var:02x}", f"{dvar:02x}"
    src_model = f"model\\hm\\hm{s}\\{pfx}{s}{sv}\\{pfx}{s}{sv}"
    dst_model = f"model\\hm\\hmf6\\{pfx}f6{dv}\\{pfx}f6{dv}"
    pairs = [(src_model, dst_model),
             (f"hm{s}\\{pfx}{s}{sv}", f"hm{d}\\{pfx}{d}{dv}"), (f"{pfx}{s}{sv}", f"{pfx}{d}{dv}")]
    return [(a.encode(), b.encode()) for a, b in pairs]


def clone_arc(src_arc, dst_arc, pairs, tint):
    work = tempfile.mkdtemp(prefix="lp2dlc")
    try:
        sys.argv = ["arcx", "x", src_arc, os.path.join(work, "in")]
        arcx.main()
        lines = open(os.path.join(work, "in", ".arcorder"), encoding="latin-1").read().splitlines()
        outdir = os.path.join(work, "out")
        order = []
        for ln in lines:
            name, cls = ln.split("\t")
            data = open(os.path.join(work, "in", *name.split("\\")) + "." + cls, "rb").read()
            new = name.encode("latin-1")
            for a, b in pairs:
                new = new.replace(a, b)
                data = data.replace(a, b)  # same length, so offsets inside the file stay valid
            if tint and cls == "rTexture" and "_BM" in name:
                data = tint_texture(data, tint)
            new = new.decode("latin-1")
            p = os.path.join(outdir, *new.split("\\")) + "." + cls
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(data)
            order.append(f"{new}\t{cls}\n")
        open(os.path.join(outdir, ".arcorder"), "w", encoding="latin-1").writelines(order)
        return arcx.pack(outdir, dst_arc)
    finally:
        shutil.rmtree(work)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, help="the game's nativePC folder")
    ap.add_argument("--src", required=True)
    ap.add_argument("--item", type=int)
    ap.add_argument("--name", default="Mod Part")
    ap.add_argument("--tint", choices=sorted(TINTS))
    ap.add_argument("out")
    a = ap.parse_args()
    entries = []
    for spec in a.src.split(","):
        spec, _, name = spec.strip().partition("=")
        src, _, item = spec.partition("@")
        item = int(item) if item else a.item
        if item is None:
            raise SystemExit(f"{src}: no slot (use --item or {src}@N)")
        entries.append(build_part(a, src, item, name or a.name))
    sb = os.path.join(a.out, "Content", "nativePC", "sname.bin")
    open(sb, "wb").write(snamebin.build(entries))
    print("wrote", sb, f"({len(entries)} entries)")


def build_part(a, src, item, name):
    pfx, sset, var = src[:2], int(src[2:4], 16), int(src[4:6], 16)
    if pfx not in CAT or not 0 <= item < 70:
        raise SystemExit("bad --src or --item")
    base = os.path.join(a.game, "arcXmlTmpPC", "CustomParts")
    dst = os.path.join(a.out, "Content", "nativePC", "arcXmlTmpPC", "CustomParts")
    os.makedirs(dst, exist_ok=True)
    for dset in (0x0E, 0x2E):
        pairs = rename_pairs(pfx, sset, var, dset, item)
        tag = f"{pfx}{dset:02x}{item:02x}"
        n = clone_arc(os.path.join(base, src + ".arc"), os.path.join(dst, tag + ".arc"), pairs, a.tint)
        print(f"{tag}.arc: {n} entries")
        for col in range(4):
            colsrc = os.path.join(base, f"{src}{col:02x}.arc")
            if os.path.exists(colsrc):
                n = clone_arc(colsrc, os.path.join(dst, f"{tag}{col:02x}.arc"), pairs, a.tint)
                print(f"{tag}{col:02x}.arc: {n} entries")
    cat = CAT[pfx]
    entry = {"category": cat, "item": item, "names": [name[:43]] * 7}
    entry["floats"] = [0.0] * snamebin.FLOATS[{v: k for k, v in snamebin.CATS.items()}[cat]]
    return entry


if __name__ == "__main__":
    main()
