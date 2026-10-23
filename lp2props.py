#!/usr/bin/env python3
"""LP2's object models (uOm archives: crates, walls, barricades, ...) as one asset library map of props.

  lp2props.py --game LP2_DIR LIB

Every uOm*.arc's rModels (top LOD, meshes with UVs and a colour map) are converted to the static stage format
(lp2stage.py: 0x49B4F022) and laid out on a grid in one stage, LIB/lp2/props/.preview/stage/<STAGE_DIR>/
online00.rModel, with their rTextures beside it (copied as they are; names are the archives' own leaves) and the
editor preview (lp2preview.write_geo) whose piece tree is one piece per model, named after it. Collision: each
model's triangles, as LP1 SBC1 (lp2col.write_sbc1) in LIB/lp2/props/assets/props.sbc1 (move and bullet).
So placing a prop is placing a piece of another map: lp2pieces.merge_foreign / foreign_collision do the rest.

Vertex: positions are model space (rigid meshes too: their bone index only drives breaking / animation), normal
from the format's offset (mod2obj.NORMAL_OFF) or the faces, tangent from the UVs, baked light a little top light
(LIGHT_* below: stages have no lighting of their own for these models). Kept: models named om*, once each (archives
share shells / debris / akrid parts); skipped: VS parts, effect models (_efc), models with no textured mesh. Index entry (lp2library.py): {key "lp2_props", group "Props", map "lp2/props"}.
"""
import argparse, json, os, re, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2col, lp2mapc, lp2pieces, lp2preview, mod2obj  # noqa: E402

REL = "lp2/props"
GAP, ROW = 1000.0, 20000.0  # cm between models, row width
LIGHT_BASE, LIGHT_UP = 104, 40  # baked light: base + up * normal.y (128 = the LP1 maps' unlit grey)


def progress(f, text=""):
    print(f"@progress {f:.3f} {text}", flush=True)


def face_normals(P, T):
    n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    out = np.zeros_like(P)
    for k in range(3):
        np.add.at(out, T[:, k], n)
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def tangents(P, U, N, T):
    """per-vertex tangent from the UV gradient, made orthogonal to the normal"""
    e1, e2 = P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]
    d1, d2 = U[T[:, 1]] - U[T[:, 0]], U[T[:, 2]] - U[T[:, 0]]
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 0.0, 1.0 / np.where(r == 0, 1, r))
    t = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
    out = np.zeros_like(P)
    for k in range(3):
        np.add.at(out, T[:, k], t)
    out -= N * (out * N).sum(1, keepdims=True)
    bad = np.linalg.norm(out, axis=1) < 1e-9
    out[bad] = np.cross(N[bad], [0.0, 1.0, 0.0]) + np.cross(N[bad], [0.0, 0.0, 1.0]) * 1e-3
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def stage_verts(P, N, Tg, U):
    v = np.zeros((len(P), 28), np.uint8)
    v[:, :12] = P.astype("<f4").view(np.uint8).reshape(-1, 12)
    v[:, 12:15] = lp2pieces.u8n(N)
    v[:, 15] = 255
    v[:, 16:19] = lp2pieces.u8n(Tg)
    v[:, 19] = 255
    v[:, 20:24] = U.astype("<f2").view(np.uint8).reshape(-1, 4)
    light = np.clip(LIGHT_BASE + LIGHT_UP * N[:, 1], 0, 255).astype(np.uint8)
    v[:, 24:27] = light[:, None]
    v[:, 27] = 255
    return v


def model_meshes(b):
    """an object rModel -> (name list of its textures, [dict(mat, P, N, U, T)]) for top-LOD meshes with UVs"""
    M = mod2obj.read_model(b)
    nt, ot = struct.unpack_from("<I", b, 0x1C)[0], struct.unpack_from("<I", b, 0x2C)[0]
    names = [b[ot + i * 64:ot + i * 64 + 64].split(b"\0")[0].decode() for i in range(nt)]
    mats = [struct.unpack_from("<12I", b, ot + nt * 64 + i * 160) for i in range(struct.unpack_from("<H", b, 0x0A)[0])]
    out = []
    for m in M["meshes"]:
        _, uv_off = mod2obj.LAYOUTS.get(m["fmt"], (None, None))
        if not m["lodmask"] & 1 or uv_off is None or m["mat"] >= len(mats) or not 0 < mats[m["mat"]][3] <= nt:
            continue
        g = mod2obj.mesh_geometry(b, m, M)
        if not g or not g[2]:
            continue
        verts, uvs, tris = g
        ids = sorted(verts)
        remap = {v: k for k, v in enumerate(ids)}
        P = np.array([verts[i] for i in ids], np.float64)
        U = np.array([(uvs[i][0], 1.0 - uvs[i][1]) for i in ids], np.float64)   # back to the file's V
        T = np.array([[remap[i] for i in t] for t in tris], np.int64)
        if not np.isfinite(P).all() or not np.isfinite(U).all():
            continue
        N = None
        if mod2obj.NORMAL_OFF.get(m["fmt"]) is not None:
            base, off = M["vb"] + m["voff"], mod2obj.NORMAL_OFF[m["fmt"]]
            N = np.array([[(x - 127) / 127.0 for x in b[base + (m["vbase"] + i) * m["stride"] + off:][:3]] for i in ids])
            if (np.linalg.norm(N, axis=1) < 0.5).mean() > 0.1:
                N = None
        if N is None:
            N = face_normals(P, T)
        out.append(dict(mat=m["mat"], slots=mats[m["mat"]][3:6], P=P, N=N, U=U, T=T))
    return names, out


def stage_template(game):
    """the stock online00 stage: (its first material record, its CM texture name)"""
    stock = lp2mapc.entries(os.path.join(game, "nativePC", lp2mapc.ARCS["scr"]))
    tb = next(d for n, d in stock["rModel"] if lp2mapc.base(n).lower() == "online00")
    nt, ot = struct.unpack_from("<I", tb, 0x1C)[0], struct.unpack_from("<I", tb, 0x2C)[0]
    names = [tb[ot + i * 64:ot + i * 64 + 64].split(b"\0")[0].decode() for i in range(nt)]
    mat = bytes(tb[ot + nt * 64:ot + nt * 64 + 160])
    return mat, names[struct.unpack_from("<I", mat, 36)[0] - 1], tb


def build(game, lib, log=print):
    import glob
    folder = os.path.join(lib, *REL.split("/"))
    prev = os.path.join(folder, ".preview")
    out_dir = os.path.join(prev, "stage", *lp2mapc.STAGE_DIR.split("\\"))
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(folder, "assets"), exist_ok=True)
    mat_tpl, cm_name, tb = stage_template(game)
    open(os.path.join(prev, "online00.rModel"), "wb").write(tb)
    textures, tex_index = [cm_name], {cm_name.lower(): 1}
    materials, mat_key, meshes, props, col = [], {}, [], [], []
    tex_files, seen = {}, set()
    cx = cz = row_d = 0.0
    arcs = sorted(glob.glob(os.path.join(game, "nativePC", "arcLp2Xml", "autoArc", "uOm*.arc")))
    for k, arc in enumerate(arcs):
        progress(0.7 * (k + 1) / len(arcs), os.path.basename(arc))
        if os.path.getsize(arc) < 1024 or "vsparts" in arc.lower():
            continue
        ent = lp2mapc.entries(arc)
        texs = {lp2mapc.base(n).lower(): d for n, d in ent.get("rTexture", [])}
        for name, b in ent.get("rModel", []):
            leaf = lp2mapc.base(name)
            if not leaf.lower().startswith("om") or re.search(r"_efc", leaf, re.I) or leaf.lower() in seen:
                continue   # object models only (archives also carry shells, debris effects, akrid parts), once each
            seen.add(leaf.lower())
            try:
                names, ms = model_meshes(b)
            except Exception as e:   # noqa: BLE001 (a format we don't read: leave the model out)
                log(f"  {leaf}: skipped ({e})")
                continue
            ms = [m for m in ms if names[m["slots"][0] - 1].split("\\")[-1].lower() in texs]
            if not ms:
                continue
            lo = np.min([m["P"].min(0) for m in ms], 0)
            hi = np.max([m["P"].max(0) for m in ms], 0)
            w, d = hi[0] - lo[0], hi[2] - lo[2]
            if cx and cx + w > ROW:
                cx, cz, row_d = 0.0, cz + row_d + GAP, 0.0
            shift = np.array([cx - lo[0], -lo[1], cz - lo[2]])
            cx += w + GAP
            row_d = max(row_d, d)
            cverts, ctris = [], []
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
                P = m["P"] + shift
                Tg = tangents(P, m["U"], m["N"], m["T"])
                meshes.append(dict(mat=mat_key[key], verts=stage_verts(P, m["N"], Tg, m["U"]), tris=m["T"]))
                ctris += [(tuple(int(x) + len(cverts) for x in t), 0) for t in m["T"]]
                cverts += [tuple(x) for x in P]
            for i in range(0, len(ctris), 20000):   # SBC groups: at most 65535 vertices
                part = ctris[i:i + 20000]
                used = sorted({x for t, _ in part for x in t})
                rm = {v: j for j, v in enumerate(used)}
                col.append(dict(verts=[cverts[v] for v in used], tris=[(tuple(rm[x] for x in t), 0) for t, _ in part]))
            props.append(dict(name=leaf, arc=os.path.basename(arc), box=((lo + shift).tolist(), (hi + shift).tolist())))
    progress(0.72, "stage model")
    by_mat = {}   # one mesh per material (mesh records hold a 12-bit group id: at most 4095 meshes)
    for m in meshes:
        by_mat.setdefault(m["mat"], []).append(m)
    meshes = []
    for mat, ms in by_mat.items():
        base = np.cumsum([0] + [len(m["verts"]) for m in ms[:-1]])
        meshes.append(dict(mat=mat, verts=np.concatenate([m["verts"] for m in ms]),
                           tris=np.concatenate([m["tris"] + o for m, o in zip(ms, base)])))
    model = os.path.join(out_dir, "online00.rModel")
    from lp2stage import write_stage
    write_stage(model, textures, materials, meshes)
    open(os.path.join(folder, "assets", "props.sbc1"), "wb").write(lp2col.write_sbc1(col))
    progress(0.75, "pieces")
    S = lp2pieces.read_stage(model)
    per_mesh, n = lp2pieces.atoms(S)
    stats = lp2preview.write_geo(prev, S, per_mesh, n, tex_files, 256, log)
    # the piece tree: one piece per model (an atom goes with the model whose box holds its centre)
    alo, ahi, _ = lp2pieces.atom_boxes(S, per_mesh, n)
    c = (alo + ahi) / 2
    tree = []
    for p in props:
        lo, hi = np.array(p["box"][0]) - 1, np.array(p["box"][1]) + 1
        inside = np.nonzero(((c >= lo) & (c <= hi)).all(1))[0]
        if len(inside):
            tree.append(dict(name=p["name"], atoms=inside.tolist()))
    g = json.load(open(os.path.join(prev, "geo.json")))
    g["tree"] = tree
    stats["model_bytes"] = os.path.getsize(model)
    g["stats"] = stats
    json.dump(g, open(os.path.join(prev, "geo.json"), "w"), separators=(",", ":"))
    project = {"format": "lp2map", "version": 1, "info": {"name": "LP2 objects", "tag": "lp2props_"},
               "base": {"stock": 0}, "stage": {"props": True},
               "collision": {"lp1_move": "assets/props.sbc1", "lp1_bullet": "assets/props.sbc1"},
               "props": [dict(name=p["name"], arc=p["arc"]) for p in props]}
    json.dump(project, open(os.path.join(folder, "project.json"), "w"), indent=1)
    progress(1.0, "done")
    log(f"{REL}: {len(tree)} props, {len(meshes)} meshes, {len(textures)} textures, {stats['vertices']} vertices, "
        f"{os.path.getsize(model) / 1e6:.1f} MB stage")
    return dict(key="lp2_props", name="LP2 objects", source="LP2", group="Props", map=REL)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("lib")
    a = ap.parse_args()
    print(json.dumps(build(a.game, a.lib)))


if __name__ == "__main__":
    main()
