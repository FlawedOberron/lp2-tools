#!/usr/bin/env python3
"""LP2's own online maps as asset library maps, so the editor can place their pieces (as LP1 maps' pieces).

  lp2stockmaps.py --game LP2_DIR LIB [NN ...]     every stock online map (or the ones given), LIB/lp2/mapNN

Each map's stage models (aArea_ONLINE_NN_scr.arc rModels; not skies, shadow casters) are converted to the static
stage format (lp2stage.py: 0x49B4F022) in place (stage models are in map space), top LOD, meshes with a colour map,
as lp2props.py converts objects (its model_meshes / stage_verts: the stock lightmaps aren't kept; a built map's
bake relights copied pieces). One stage, LIB/lp2/mapNN/.preview/stage/<STAGE_DIR>/online00.rModel, with the
models' rTextures beside it, and the editor preview (lp2preview.write_geo, default piece tree).
Collision: the map's atari* (move) and tama* (bullet) rCollision from aArea_ONLINE_NN_v.arc (every map has them
there; some _scr arcs don't) as LP1 SBC1 (lp2col.write_sbc1), surfaces kept: plain -> 0x3fffff00, 0x4000xxxx
materials -> 0x8000xxxx (lp2col maps them back; ones the built map's table lacks become its first surface).
Index entry (lp2library.py): {key "lp2_mapNN", name "LP2 map <name>", source "LP2", group "Maps", map "lp2/mapNN"}.
Nothing from the game is shipped: the library is made from the user's own install.
"""
import argparse, glob, json, os, re, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2col, lp2mapc, lp2pieces, lp2preview, lp2props, sbc  # noqa: E402
from lp2sky import NAMES  # noqa: E402

SKIP = re.compile(r"sky|shadow|kage", re.I)   # sky domes and shadow casters
GROUP_TRIS = 20000                             # SBC1 groups: at most 65535 vertices


def progress(f, text=""):
    print(f"@progress {f:.3f} {text}", flush=True)


def numbers(game):
    arcs = glob.glob(os.path.join(game, "nativePC", "arcLp2Xml", "autoArc", "aArea_ONLINE_??_scr.arc"))
    return sorted(os.path.basename(a)[13:15] for a in arcs)


def rel(num):
    return f"lp2/map{num}"


def entry(num):
    return dict(key=f"lp2_map{num}", name=f"LP2 map {NAMES.get(num, num)}", source="LP2", group="Maps", map=rel(num))


def sbc1_flags(f):
    """an LP2 surface's flags -> LP1's (lp2col.py maps them back)"""
    if f & 0x40000000:
        return (f & 0x3FFFFFFF) | 0x80000000
    return 0x3FFFFF00


def collision(b):
    """an LP2 rCollision -> SBC1 groups (lp2col.write_sbc1)"""
    c = sbc.read(b)
    out = []
    starts = [g["vert"] for g in c["groups"]] + [len(c["verts"])]
    for gi, g in enumerate(c["groups"]):
        verts = c["verts"][starts[gi]:starts[gi + 1]]
        tris = [((t[3], t[4], t[5]), sbc1_flags(c["surfaces"][t[6]])) for t in c["tris"][g["tri"]:g["tri_end"]]]
        for i in range(0, len(tris), GROUP_TRIS):
            part = tris[i:i + GROUP_TRIS]
            used = sorted({x for t, _ in part for x in t})
            rm = {v: j for j, v in enumerate(used)}
            out.append(dict(verts=[verts[v] for v in used], tris=[(tuple(rm[x] for x in t), s) for t, s in part]))
    return out


def build(game, lib, num, log=print, span=(0.0, 1.0)):
    at = lambda f: span[0] + (span[1] - span[0]) * f
    name = entry(num)["name"]
    folder = os.path.join(lib, *rel(num).split("/"))
    prev = os.path.join(folder, ".preview")
    out_dir = os.path.join(prev, "stage", *lp2mapc.STAGE_DIR.split("\\"))
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(folder, "assets"), exist_ok=True)
    auto = os.path.join(game, "nativePC", "arcLp2Xml", "autoArc")
    scr = lp2mapc.entries(os.path.join(auto, f"aArea_ONLINE_{num}_scr.arc"))
    var = lp2mapc.entries(os.path.join(game, "nativePC", "arcXmlTmpPC", "variable", f"aArea_ONLINE_{num}_v.arc"))
    texs = {}
    for ent in (var, scr):
        texs.update({lp2mapc.base(n).lower(): d for n, d in ent.get("rTexture", [])})
    mat_tpl, cm_name, _ = lp2props.stage_template(game)
    textures, tex_index, tex_files = [cm_name], {cm_name.lower(): 1}, {}
    materials, mat_key, meshes, models = [], {}, [], []
    todo = [(n, b) for n, b in scr.get("rModel", []) if not SKIP.search(lp2mapc.base(n))]
    for k, (mname, b) in enumerate(todo):
        leaf = lp2mapc.base(mname)
        progress(at(0.6 * k / max(1, len(todo))), f"{name}: {leaf}")
        try:
            names, ms = lp2props.model_meshes(b)
        except Exception as e:   # noqa: BLE001 (a format we don't read: leave the model out)
            log(f"  {leaf}: skipped ({e})")
            continue
        ms = [m for m in ms if names[m["slots"][0] - 1].split("\\")[-1].lower() in texs]
        for m in ms:
            key = (leaf.lower(), m["mat"])
            if key not in mat_key:
                slot = []
                for s in m["slots"]:
                    tn = names[s - 1].split("\\")[-1] if 0 < s <= len(names) else ""
                    if tn.lower() not in texs:
                        slot.append(0)
                        continue
                    full = lp2mapc.STAGE_DIR + "\\" + tn
                    if full.lower() not in tex_index:
                        p = os.path.join(out_dir, tn + ".rTexture")
                        open(p, "wb").write(texs[tn.lower()])
                        textures.append(full)
                        tex_index[full.lower()] = len(textures)
                        tex_files[full.lower()] = p
                    slot.append(tex_index[full.lower()])
                rec = bytearray(mat_tpl)
                struct.pack_into("<3I", rec, 12, *slot)
                struct.pack_into("<I", rec, 36, 1)
                materials.append(bytes(rec))
                mat_key[key] = len(materials) - 1
            Tg = lp2props.tangents(m["P"], m["U"], m["N"], m["T"])
            meshes.append(dict(mat=mat_key[key], verts=lp2props.stage_verts(m["P"], m["N"], Tg, m["U"]), tris=m["T"]))
        if ms:
            models.append(leaf)
    if not meshes:
        raise SystemExit(f"{name}: no stage meshes read")
    progress(at(0.62), f"{name}: stage model")
    by_mat = {}   # one mesh per material, split to stay within 16-bit indices
    for m in meshes:
        by_mat.setdefault(m["mat"], []).append(m)
    meshes = []
    for mat, ms in by_mat.items():
        cur, n = [], 0
        for m in ms + [None]:
            if m is None or (cur and n + len(m["verts"]) > 65535):
                base = np.cumsum([0] + [len(x["verts"]) for x in cur[:-1]])
                meshes.append(dict(mat=mat, verts=np.concatenate([x["verts"] for x in cur]),
                                   tris=np.concatenate([x["tris"] + o for x, o in zip(cur, base)])))
                cur, n = [], 0
            if m is not None:
                cur.append(m)
                n += len(m["verts"])
    model = os.path.join(out_dir, "online00.rModel")
    from lp2stage import write_stage
    write_stage(model, textures, materials, meshes)
    progress(at(0.7), f"{name}: collision")
    col = {}
    for cname, b in var.get("rCollision", []):
        leaf = lp2mapc.base(cname).lower()
        kind = "move" if leaf.startswith("atari") else "bullet" if leaf.startswith("tama") else None
        if kind and kind not in col:
            col[kind] = collision(b)
            open(os.path.join(folder, "assets", f"{kind}.sbc1"), "wb").write(lp2col.write_sbc1(col[kind]))
    progress(at(0.75), f"{name}: preview")
    S = lp2pieces.read_stage(model)
    per_mesh, n = lp2pieces.atoms(S)
    stats = lp2preview.write_geo(prev, S, per_mesh, n, tex_files, 256, log)
    g = json.load(open(os.path.join(prev, "geo.json")))
    stats["model_bytes"] = os.path.getsize(model)
    g["stats"] = stats
    json.dump(g, open(os.path.join(prev, "geo.json"), "w"), separators=(",", ":"))
    project = {"format": "lp2map", "version": 1, "info": {"name": name, "tag": f"lp2map{num}"},
               "base": {"stock": int(num)}, "stage": {"stock_map": int(num), "models": models},
               "collision": {k: f"assets/{v}.sbc1" for k, v in (("lp1_move", "move"), ("lp1_bullet", "bullet")) if v in col}}
    json.dump(project, open(os.path.join(folder, "project.json"), "w"), indent=1)
    progress(at(1.0), f"{name}: done")
    log(f"{rel(num)}: {len(models)} models, {len(meshes)} meshes, {len(textures)} textures, {stats['vertices']} vertices, "
        f"{n} atoms, collision {', '.join(sorted(col)) or 'none'}, {os.path.getsize(model) / 1e6:.1f} MB stage")
    return entry(num)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("lib")
    ap.add_argument("maps", nargs="*")
    a = ap.parse_args()
    for num in a.maps or numbers(a.game):
        build(a.game, os.path.abspath(a.lib), num)


if __name__ == "__main__":
    main()
