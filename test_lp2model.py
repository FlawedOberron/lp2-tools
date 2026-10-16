#!/usr/bin/env python3
"""Rebuild shipped part models through lp2model and check the result decodes to the same data.
  test_lp2model.py PART.rModel [...]"""
import math, struct, sys
import mod2obj as M
import lp2model as L


def decode(path):
    b = open(path, "rb").read()
    Mdl = M.read_model(b)
    bones, _ = M.read_bones(b)
    meshes = []
    for m in Mdl["meshes"]:
        if m["fmt"] != L.FMT_SKIN:
            continue
        idx = struct.unpack_from(f"<{m['icount']}H", b, Mdl["ib"] + m["istart"] * 2)
        used = sorted(set(idx))
        geo = M.mesh_geometry(b, m, Mdl)
        remap = {i: n for n, i in enumerate(used)}
        verts = []
        for i in used:
            v = b[Mdl["vb"] + m["voff"] + (m["vbase"] + i) * 28:][:28]
            n = [(x - 127) / 127 for x in v[8:11]]
            t = [(x - 127) / 127 for x in v[12:15]] + [1 if v[15] else -1]
            u, vv = struct.unpack_from("<2e", v, 20)
            ws = [(bones[bi]["joint"], w) for bi, w in M.vertex_skin(v, "w4")]
            verts.append(dict(pos=geo[0][i], normal=n, tangent=t, uv=(u, 1 - vv), weights=ws))
        tris = [tuple(remap[i] for i in t) for t in M.list_tris(idx)]
        meshes.append(dict(group=m["group"], mat=m["mat"], lodmask=m["lodmask"], verts=verts, tris=tris))
    return b, Mdl, meshes


def check(path):
    b, Mdl, meshes = decode(path)
    tpl = L.read_template(b)
    out, rep = L.build_model(tpl, [], meshes)
    b2, Mdl2, meshes2 = decode_bytes(out)
    S = Mdl["qscale"]
    perr = max(math.dist(v1["pos"], v2["pos"]) for m1, m2 in zip(meshes, meshes2) for v1, v2 in zip(m1["verts"], m2["verts"]))
    werr = 0
    for m1, m2 in zip(meshes, meshes2):
        for v1, v2 in zip(m1["verts"], m2["verts"]):
            d1, d2 = dict(v1["weights"]), dict(v2["weights"])
            werr = max(werr, max(abs(d1.get(k, 0) - d2.get(k, 0)) for k in set(d1) | set(d2)))
    terr = sum(1 for m1, m2 in zip(meshes, meshes2) if m1["tris"] != m2["tris"])
    # bones / inverse binds identical to the original's
    nb = len(tpl["bones"])
    o1, o2 = struct.unpack_from("<I", b, 0x24)[0], struct.unpack_from("<I", out, 0x24)[0]
    loc_same = b[o1 + nb * 24:o1 + nb * 88] == out[o2 + nb * 24:o2 + nb * 88]
    ib1 = struct.unpack_from(f"<{nb*16}f", b, o1 + nb * 88)
    ib2 = struct.unpack_from(f"<{nb*16}f", out, o2 + nb * 88)
    remap_same = b[o1 + nb * 152:o1 + nb * 152 + 256] == out[o2 + nb * 152:o2 + nb * 152 + 256]
    recs_same = all(b[o1 + i * 24:o1 + i * 24 + 3] == out[o2 + i * 24:o2 + i * 24 + 3] for i in range(nb))
    print(f"{path.split('/')[-1]}: {rep['meshes']} meshes {rep['vertices']} verts {rep['bytes']} B | pos err {perr:.4f} cm "
          f"(step {S/32767:.4f}) | weight err {werr:.4f} | tri lists differ {terr} | local mats same {loc_same} "
          f"| invbind max diff {max(abs(x-y) for x,y in zip(ib1,ib2)):.4f} | remap same {remap_same} | bone recs same {recs_same}")
    print("   header sphere/bbox orig", [round(x, 2) for x in struct.unpack_from("<4f3f", b, 0x40)[:4]],
          "new", [round(x, 2) for x in struct.unpack_from("<4f", out, 0x40)])
    return out


def decode_bytes(out):
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".rModel", delete=False) as f:
        f.write(out)
    try:
        return decode(f.name)
    finally:
        os.unlink(f.name)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        check(p)
