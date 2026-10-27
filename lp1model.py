#!/usr/bin/env python3
"""Lost Planet 1 (Extreme Condition PC) rModel (MT 'MOD\\0' v0x99) reader -> OBJ + MTL + DDS.
  lp1model.py MODEL OUT.obj [--all-lods]      textures are looked up next to MODEL, in the arcx
                                              tree (<name>.0x3cad8076), and written as DDS beside OUT.obj
Header: 0x04 u16 version (0x99), 0x06 u16 bones, 0x08 u16 meshes, 0x0A u16 materials,
  0x0C vertex count, 0x10 index count, 0x14 ?, 0x18 vertex buffer size, 0x20 texture count,
  0x24 group count, offsets: 0x2C bones, 0x30 groups (32 B), 0x34 textures (64-byte names) then
  materials (160 B), 0x38 meshes (52 B) then u32 N + N*144 B palette records, 0x3C vertex buffer,
  0x44 index buffer (u16 triangle STRIPS, absolute vertex indices).
  0x60 bbox min xyz, 0x70 bbox max xyz.
Bones: same as LP2 (n*24 records: joint, parent; n local; n inverse-bind; 256-byte remap).
Material: u32[6..8] = 1-based texture slots (diffuse, normal, mask); 0 = none (shadow material).
Mesh (52 B): +0 u16 part group, +2 u16 material, +5 u8 LOD mask (0x01 hi, 0xfe lower),
  +7 u8 skin type (1 rigid, 2/3 skinned), +12 u16 vertex count, +14 u16 last vertex,
  +16 u32 first vertex, +20 u32 vertex buffer byte offset, +24 u32 byte offset into the second
  buffer, +28 u32 index start, +32 u32 index count, +44 u32 (low byte) palette size.
Palette: the meshes take the 144-byte records after them in order, as many as their palette size;
  record +0 u32 = bone list index (+4.. bounds). Vertex bone index k = the mesh's k-th record.
  Vertex for index i is at vb + offset + i*32. Mesh +9 == 8 (skin types 5 and 8: 8 bones, faces):
  8-bone vertex, below, plus 8 bytes per vertex in a second buffer (header 0x40, size 0x1C) at
  +24 offset: UV copy + tangent.
Vertex (32 B): +0 int16x3 position (each axis 0..32767 over the bbox) + int16 32767,
  +8 u8x4 bone indices, +12 u8x4 weights (/255), +16 u8x4 normal ((b - 127) / 127),
  +20 u8x4 tangent, +24 f16x2 UV, +28 f16x2 UV (copy).
8-bone vertex (32 B): +0 position as above, +8 u8x8 bone indices, +16 u8x8 weights, +24 u8x4 normal,
  +28 f16x2 UV.
Stage models (no bones, scr\\stage*): 32-byte vertex = f32x3 position (cm), +12 normal (as below),
  +16 tangent, +20 f16x2 UV, +24 UV copy, +28 f16x2 second UV (lightmap).
Xbox 360 (Colonies): '\0DOM', everything big-endian, same layout, except per vertex: position
  u16x3 0..65535 over the bbox, indices/weights byte-reversed, normal packed DEC3N (10:10:10 signed,
  x in the low bits of a big-endian u32). Index strips may use 0xFFFF as a restart.
"""
import os, struct, sys

TEX_HASH = "0x3cad8076"


def endian(b):
    if b[:4] == b"MOD\0":
        return "<"
    if b[:4] == b"\0DOM":
        return ">"
    raise ValueError("not a MOD file")


def read_bones(b):
    e = endian(b)
    n = struct.unpack_from(e + "H", b, 6)[0]
    off = struct.unpack_from(e + "I", b, 0x2C)[0]
    bones = []
    for i in range(n):
        joint, parent = b[off + i * 24], b[off + i * 24 + 1]
        local = struct.unpack_from(e + "16f", b, off + n * 24 + i * 64)
        inv = struct.unpack_from(e + "16f", b, off + n * 88 + i * 64)
        bones.append(dict(joint=joint, parent=parent, local=local, invbind=inv))
    return bones


# Vertex bone indices go through each mesh's palette (read_model: m["pal"] = joint ids, in bone
# list order): the mesh's k-th smallest index is its k-th palette bone. Gameplay models number
# vertex bones through the whole bone list less the never-skinned end joints (so the pairing is
# the same everywhere); cutscene models (hm05 Basil) use sparse per-mesh numbers.
UNSKINNED = (19, 20, 21)


def skin_joints(bones):
    """vertex bone index -> joint number"""
    return [bn["joint"] for bn in bones if bn["joint"] not in UNSKINNED]


def read_model(b):
    E = endian(b)
    if struct.unpack_from(E + "H", b, 4)[0] != 0x99:
        raise ValueError("not an LP1 MOD v0x99")
    nbones, nmesh, nmat = struct.unpack_from(E + "HHH", b, 6)
    nvert = struct.unpack_from(E + "I", b, 0x0C)[0]
    ntex = struct.unpack_from(E + "I", b, 0x20)[0]
    tex_off, mesh_off, vb = struct.unpack_from(E + "III", b, 0x34)
    ib = struct.unpack_from(E + "I", b, 0x44)[0]
    bmin = struct.unpack_from(E + "3f", b, 0x60)
    bmax = struct.unpack_from(E + "3f", b, 0x70)
    texs = [b[tex_off + i * 64:tex_off + i * 64 + 64].split(b"\0")[0].decode("latin-1") for i in range(ntex)]
    mat_off = tex_off + ntex * 64
    mats = [struct.unpack_from(E + "3I", b, mat_off + i * 160 + 24) for i in range(nmat)]
    bone_off = struct.unpack_from(E + "I", b, 0x2C)[0]
    joints = [b[bone_off + i * 24] for i in range(nbones)]
    pal_off = mesh_off + nmesh * 52 + 4
    meshes = []
    for k in range(nmesh):
        e = mesh_off + k * 52
        group, mat = struct.unpack_from(E + "HH", b, e)
        vc, _last, vstart = struct.unpack_from(E + "HHI", b, e + 12)
        voff, voff2, istart, icount = struct.unpack_from(E + "IIII", b, e + 20)
        meshes.append(dict(group=group, mat=mat, lodmask=b[e + 5], skin=b[e + 7], w8=b[e + 9] == 8, vc=vc, vstart=vstart, voff=voff, voff2=voff2,
                           istart=istart, icount=icount))
        npal = struct.unpack_from(E + "I", b, e + 44)[0] & 0xFF
        recs = [struct.unpack_from(E + "I", b, pal_off + r * 144)[0] for r in range(npal)]
        meshes[-1]["pal"] = [joints[r] for r in recs] if all(r < nbones for r in recs) else []  # stages: no bones
        pal_off += npal * 144
    if nbones == 0:  # stages: u16 indices, so vstart wraps every ~64K vertices; the new group follows the last
        base, end, prev = 0, 0, None
        for m in meshes:
            if prev is None or m["voff"] != prev["voff"]:
                base, end = 0, 0
            elif m["vstart"] < prev["vstart"]:
                base, end = base + end * 32, 0
            end = max(end, m["vstart"] + m["vc"])
            prev = dict(m)
            m["voff"] += base
    return dict(e=E, bones=nbones, nvert=nvert, texs=texs, mats=mats, meshes=meshes, vb=vb, ib=ib, bmin=bmin, bmax=bmax)


def strip_tris(idx):
    start = 0  # winding parity restarts after a 0xFFFF strip restart
    for j in range(len(idx) - 2):
        a, b_, c = idx[j], idx[j + 1], idx[j + 2]
        if a == 0xFFFF:
            start = j + 1
        if 0xFFFF in (a, b_, c) or a == b_ or b_ == c or a == c:
            continue
        yield (a, b_, c) if (j - start) % 2 == 0 else (b_, a, c)


def vertex(b, M, m, i):
    """-> (pos, normal, uv (bottom-up), [(joint id, weight)])"""
    pos, n, uv, raw = _vertex(b, M, m, i)
    if "rawmap" not in m:
        used = sorted({r for t in mesh_geometry(b, M, m) for k in t for r, _w in _vertex(b, M, m, k)[3]})
        if not m["pal"]:  # unskinned (stage geometry)
            m["rawmap"] = {r: 0 for r in used}
        elif len(used) > len(m["pal"]):
            raise ValueError(f"mesh uses {len(used)} bone indices, palette has {len(m['pal'])}")
        else:
            m["rawmap"] = dict(zip(used, m["pal"]))
    # a vertex no triangle uses (VS models have some) can carry indices the palette scan never saw: bone 0
    return pos, n, uv, [(m["rawmap"].get(r, 0), w) for r, w in raw]


def _vertex(b, M, m, i):
    o = M["vb"] + m["voff"] + i * 32
    if M["bones"] == 0:  # stage geometry: f32x3 position (cm), packed normal +12, UV +20, lightmap UV +28
        E = M["e"]
        pos = struct.unpack_from(E + "3f", b, o)
        if E == ">":
            w = struct.unpack_from(">I", b, o + 12)[0]
            n = [((((w >> s) & 0x3FF) ^ 0x200) - 0x200) / 511.0 for s in (0, 10, 20)]
        else:
            n = [(x - 127) / 127.0 for x in b[o + 12:o + 15]]
        l = sum(x * x for x in n) ** 0.5 or 1.0
        u, v = struct.unpack_from(E + "2e", b, o + 20)
        return pos, tuple(x / l for x in n), (u, 1.0 - v), []
    # 4-bone: idx +8, weights +12, normal +16, UV +24; 8-bone: idx +8, weights +16, normal +24, UV +28
    ni, nw, nn, nu = (8, 16, 24, 28) if m.get("w8") else (8, 12, 16, 24)
    k = 8 if m.get("w8") else 4
    if M["e"] == "<":
        q = struct.unpack_from("<3h", b, o)
        pos = tuple(M["bmin"][a] + q[a] / 32767.0 * (M["bmax"][a] - M["bmin"][a]) for a in range(3))
        n = [(x - 127) / 127.0 for x in b[o + nn:o + nn + 3]]
        idx, ws = b[o + ni:o + ni + k], b[o + nw:o + nw + k]
    else:
        q = struct.unpack_from(">3H", b, o)
        pos = tuple(M["bmin"][a] + q[a] / 65535.0 * (M["bmax"][a] - M["bmin"][a]) for a in range(3))
        w = struct.unpack_from(">I", b, o + nn)[0]
        n = [(((w >> s) & 0x3FF) ^ 0x200) - 0x200 for s in (0, 10, 20)]
        n = [x / 511.0 for x in n]
        rev = lambda r: b"".join(r[j:j + 4][::-1] for j in range(0, len(r), 4))  # byte-reversed per 4
        idx, ws = rev(b[o + ni:o + ni + k]), rev(b[o + nw:o + nw + k])
    l = sum(x * x for x in n) ** 0.5 or 1.0
    u, v = struct.unpack_from(M["e"] + "2e", b, o + nu)
    skin = [(bi, w / 255.0) for bi, w in zip(idx, ws) if w]
    return pos, tuple(x / l for x in n), (u, 1.0 - v), skin


def mesh_geometry(b, M, m):
    idx = struct.unpack_from(f"{M['e']}{m['icount']}H", b, M["ib"] + m["istart"] * 2)
    return list(strip_tris(idx))


def find_tex(model_path, name):
    """The arcx tree root is wherever the model's own path (model\\hm\\...) starts."""
    d = os.path.dirname(os.path.abspath(model_path))
    rel = os.path.join(*name.split("\\")) + "." + TEX_HASH
    while True:
        for cand in (os.path.join(d, rel), os.path.join(d, rel.lower())):  # lp1chars lower-cases
            if os.path.exists(cand):
                return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def export_obj(src, dst, all_lods=False):
    import lp1tex
    b = open(src, "rb").read()
    M = read_model(b)
    out_dir = os.path.dirname(os.path.abspath(dst))
    stem = os.path.splitext(os.path.basename(dst))[0]
    dds = {}
    for i, t in enumerate(M["texs"]):
        p = find_tex(src, t)
        if p:
            name = t.split("\\")[-1] + ".dds"
            open(os.path.join(out_dir, name), "wb").write(lp1tex.to_dds(lp1tex.read_tex(open(p, "rb").read())))
            dds[i + 1] = name
    with open(os.path.join(out_dir, stem + ".mtl"), "w") as f:
        for i, (diff, nrm, _mask) in enumerate(M["mats"]):
            f.write(f"newmtl mat{i}\nKd 0.8 0.8 0.8\n")
            if diff in dds:
                f.write(f"map_Kd {dds[diff]}\n")
            if nrm in dds:
                f.write(f"norm {dds[nrm]}\n")
            f.write("\n")
    used = [m for m in M["meshes"] if M["mats"][m["mat"]][0] and (all_lods or m["lodmask"] & 1)]
    # vertices are keyed by (buffer offset, index): meshes with their own offset restart at 0
    verts = sorted({(m["voff"], i) for m in used for t in mesh_geometry(b, M, m) for i in t})
    index = {v: n + 1 for n, v in enumerate(verts)}
    by_off = {m["voff"]: m for m in used}
    with open(dst, "w") as f:
        f.write(f"mtllib {stem}.mtl\n")
        data = [vertex(b, M, by_off[o], i) for o, i in verts]
        for p, n, uv, _ in data:
            f.write("v %.4f %.4f %.4f\n" % p)
        for p, n, uv, _ in data:
            f.write("vt %.5f %.5f\n" % uv)
        for p, n, uv, _ in data:
            f.write("vn %.4f %.4f %.4f\n" % n)
        for k, m in enumerate(M["meshes"]):
            if m not in used:
                continue
            f.write(f"o m{k:03d}_g{m['group']}\nusemtl mat{m['mat']}\n")
            for t in mesh_geometry(b, M, m):
                f.write("f " + " ".join("{0}/{0}/{0}".format(index[(m["voff"], i)]) for i in t) + "\n")
    return len(used), len(verts)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        raise SystemExit(__doc__)
    meshes, nv = export_obj(args[0], args[1], "--all-lods" in sys.argv)
    print(f"{meshes} meshes, {nv} vertices -> {args[1]}")
