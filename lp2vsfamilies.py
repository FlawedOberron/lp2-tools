#!/usr/bin/env python3
"""VS families, weapon mounts and stock loadouts from the game's own files -> vs_families.json (beside this script),
read by lp2layout.py (a VS marker without "weapons" gets its type's stock loadout) and the Map Editor (Place: one
entry per family; inspector: variant + arm weapons).

  lp2vsfamilies.py LP2_DIR [OUT.json]

Per VS type (arcLp2Xml\\autoArc\\uVsXX.arc):
  model    the base model: the archive's first vs* model (vs00 PTX-140, vs05 GTT-11, vs06 bike / robot, ...)
  mounts   which of RA, LA, RS, LS the model has: joints 100-103 (stock maps only ever fit weapons on the arms; a
           model's 102 / 103 shoulders carry the VS's own guns, e.g. the GTT-11's autocannons)
  weapons  default loadout, 4 x [fitted, weapon id] as rObjSet group 1 stores them (lp2layout.put_object): per arm the
           weapon stock maps fit most often on this type (or on its family when the type is never placed; a Gatling
           on an arm mount neither ever fits); arms fitted in stock without a joint (vs07, vse7 ...) are built-in guns
  editable the arm mounts (RA / LA with a joint) the editor offers a weapon choice for
  stock    how many placements in every stock rObjSet (campaign + online)
Families group the types by base model; "default" is the 0x2X type (the family stock online maps use) when there is
one, else the most placed. LP1 leftovers that LP2 ships half-wired (vs50-vs84 ids: another VS's motions, wrong
seats) and types without a model are left out; lp2convert.LP1_VS maps LP1 layouts onto the families instead.
See notes/vs-mounts.md.
"""
import collections, glob, json, os, struct, sys, zlib

import arcx, mod2obj

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = 0x58A15856
LEFTOVERS = {0x50, 0x51, 0x53, 0x54, 0x55, 0x56, 0x66, 0x80, 0x81, 0x82, 0x84}
NAMES = {"vs00": "PTX-140", "vs05": "GTT-11", "vs06": "Bike / robot"}
EMPTY = [0, 0x41]   # an unfitted mount, as stock maps write it
GATLING = 0x41


def unpack(d, off, cs):
    raw = d[off:off + cs]
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def models(game):
    """-> {type: (base model, [mounts], size)}"""
    out = {}
    for a in sorted(glob.glob(os.path.join(game, "nativePC", "arcLp2Xml", "autoArc", "uVs*.arc"))):
        tag = os.path.basename(a)[3:-4]
        try:
            t = int(tag, 16)
        except ValueError:
            continue
        d = open(a, "rb").read()
        found = []
        for name, th, cs, _size, _flags, off in arcx.entries(d):
            leaf = name.split("\\")[-1].lower()
            if th == MODEL and name.lower().startswith("model\\vs") and leaf.startswith("vs") and "shadow" not in leaf:
                found.append((leaf, d, off, cs))
        if not found:
            continue
        leaf, d2, off, cs = sorted(found)[0]
        b = unpack(d2, off, cs)
        bones, _ = mod2obj.read_bones(b)
        joints = {bn["joint"] for bn in bones}
        lo, hi = struct.unpack_from("<3f", b, 0x50), struct.unpack_from("<3f", b, 0x60)
        size = [round((h - l) / 100, 1) for l, h in zip(lo, hi)]
        out[t] = (leaf, [m for m, j in zip(("RA", "LA", "RS", "LS"), (100, 101, 102, 103)) if j in joints], size)
    return out


def stock(game):
    """-> ({type: count}, {type: [Counter per mount of weapon id when fitted]})"""
    h = arcx.class_hash("rObjSet")
    count, fits, seen = collections.Counter(), collections.defaultdict(lambda: [collections.Counter() for _ in range(4)]), set()
    for a in glob.glob(os.path.join(game, "nativePC", "**", "*.arc"), recursive=True):
        d = open(a, "rb").read()
        if d[:4] != b"ARC\0":
            continue
        for name, th, cs, _size, _flags, off in arcx.entries(d):
            if th != h or name in seen:
                continue
            seen.add(name)
            b = unpack(d, off, cs)
            if b[:4] != b"OSF\0":
                continue
            n, o = struct.unpack_from("<H", b, 0x0A)[0], 0x30
            for _ in range(n):
                r = b[o:o + 0x140]
                o += 0x140
                if r[0x19] != 2:
                    continue
                t = struct.unpack_from("<H", r, 0x1A)[0]
                count[t] += 1
                for k in range(4):
                    on, cat, wid = struct.unpack_from("<BBH", r, 0x120 + 5 * k)
                    if on and cat == 4:
                        fits[t][k][wid] += 1
    return count, fits


def build(game):
    mdl = models(game)
    count, fits = stock(game)
    types, fams = {}, collections.defaultdict(list)
    for t, (model, mounts, size) in sorted(mdl.items()):
        if t in LEFTOVERS:
            continue
        fams[model].append(t)
        types[t] = dict(model=model, mounts=mounts, size=size, stock=count.get(t, 0))
    families = []
    for model, ts in sorted(fams.items()):
        fam_fits = [sum((fits[t][k] for t in ts), collections.Counter()) for k in range(4)]
        for t in ts:
            w = []
            for k, m in enumerate(("RA", "LA", "RS", "LS")):
                # what stock maps fit (also on arms without a joint: built-in guns, kept as they are); an arm
                # mount never placed in stock gets a Gatling rather than nothing; shoulders: never fitted in stock
                c = fits[t][k] if fits[t][k] else fam_fits[k]
                if k < 2 and c:
                    w.append([1, c.most_common(1)[0][0]])
                elif k < 2 and m in types[t]["mounts"]:
                    w.append([1, GATLING])
                else:
                    w.append(list(EMPTY))
            types[t]["weapons"] = w
            types[t]["editable"] = [m for m in types[t]["mounts"] if m in ("RA", "LA")]
        two = [t for t in ts if t >> 4 == 2]
        default = two[0] if two else max(ts, key=lambda t: (types[t]["stock"], -t))
        families.append(dict(name=NAMES.get(model, model), model=model, default=default, types=ts))
    return dict(families=families, types={"%02x" % t: v for t, v in types.items()})


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "vs_families.json")
    data = build(sys.argv[1])
    json.dump(data, open(out, "w"), indent=1)
    print(f"{out}: {len(data['families'])} families, {len(data['types'])} VS types")


if __name__ == "__main__":
    main()
