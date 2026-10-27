#!/usr/bin/env python3
"""Lost Planet 2 rModel (MT 'MOD\\0' v0xC5) -> Wavefront OBJ + MTL.

  mod2obj.py IN.rModel [OUT.obj]       one model
  mod2obj.py -r DIR                    every *.rModel under DIR, .obj written alongside
  mod2obj.py IN.rModel OUT.obj --pose MOTIONS.rMotionList[:N]   skinned meshes in motion N's first frame
  mod2obj.py IN.rModel OUT.obj --one-copy   only the first of a model's copies (VS weapons hold one per mount)

Header: 0x04 u16 version, 0x06 u16 bones, 0x08 u16 meshes, 0x0A u16 materials,
  0x0C vertex count, 0x10 index count, 0x18 vertex buffer size, 0x1C texture count,
  0x20 group count, offsets: 0x24 bones, 0x28 groups, 0x2C textures (64-byte names)
  then materials (160 bytes; u32[3..5] = 1-based texture slots), 0x30 meshes (48 bytes),
  0x34 vertex buffer, 0x38 index buffer (u16 triangle lists).
  0x50 bbox min xyz, 0x60 bbox max xyz (16-bit positions: min + q/32767 * S).
Mesh: +2 u16 vcount, +4 u32 (bits 0-11 part group, 12-23 material, 24-31 LOD mask: 0x01 hi, 0x02 med, 0xfc lo), +8 u8 render class (0x01/0x09/0x11/0x21..., not LOD), +10 u8 stride,
  +0x0C vertex start, +0x10 vertex buffer offset, +0x14 vertex format hash,
  +0x18 index start, +0x1C index count, +0x20 base vertex.
  Vertex for index i is at vb + offset + (base + i)*stride.
Vertex layouts were inferred per format hash; unknown formats export positions only.
"""
import os, struct, sys

# format hash -> (position encoding, uv offset or None)
#   'f32'  : 3 x float32 at 0
#   'u16q' : 3 x int16 at 0, bbox_min + q/32767 * S (S = inverse-bind diagonal)
LAYOUTS = {
    0x49B4F022: ("f32", 20), 0xB86DE023: ("f32", 24), 0x207D6030: ("f32", 16),
    0xD8297021: ("f32", 20), 0xD1A47031: ("f32", 16), 0xA7D7D02F: ("f32", 16),
    0x1255302B: ("f32", 26), 0x2082F034: ("f32", 24), 0xD4504024: ("f32", 20),
    0x747D102A: ("f32", 20), 0xA14E0035: ("f32", 20), 0x9399C02C: ("f32", None),
    0x14D40019: ("u16q", 20), 0xBDE5301A: ("u16q", 20), 0xC31F2014: ("u16q", 16),
    0x6A2E1016: ("u16q", 16), 0x01CB8011: ("u16q", 16), 0xDB7DA00D: ("u16q", 12),
    0x0CB6800E: ("u16q", None), 0xB098300C: ("u16q", None), 0xBB42401D: ("u16q", 24),
    0xA320C00F: ("u16q", None), 0xA8FAB010: ("u16q", None),
}


# format hash -> byte offset of the normal (u8 x3, (b - 127) / 127); found by matching against
# face normals. Rigid (db7da00d, b098300c) and shadow (0cb6800e) formats had no clear match.
NORMAL_OFF = {
    0x14D40019: 8, 0xBDE5301A: 8, 0xC31F2014: 8, 0x6A2E1016: 8, 0x01CB8011: 8, 0xBB42401D: 8,
    0x49B4F022: 12, 0xB86DE023: 12, 0x207D6030: 12, 0xD8297021: 12, 0xD1A47031: 12, 0xA7D7D02F: 12,
    0x1255302B: 12, 0x2082F034: 12, 0xD4504024: 12, 0x747D102A: 12, 0xA14E0035: 12, 0x9399C02C: 12,
}


def vertex_normal(v, fmt):
    off = NORMAL_OFF.get(fmt)
    if off is None:
        return None
    n = [(x - 127) / 127.0 for x in v[off:off + 3]]
    l = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) ** 0.5
    return tuple(x / l for x in n) if l > 1e-6 else None


# format hash -> skin encoding (bone indices index the model's own bone list)
#   'w4'   : idx u8x4 @16; w0 = pos.w/32767, w1 = f16 @24, w2 = f16 @26, w3 = 1 - sum
#   'w2h'  : idx as f16 @20, @22; w0 = pos.w/32767, w1 = 1 - w0
#   'r16'  : rigid, bone index in pos.w (int16)
#   'u8x4' : idx u8x4 @8, weights u8x4 @12 (/255)
SKIN = {
    0x14D40019: "w4", 0xBDE5301A: "w4", 0xC31F2014: "w2h", 0x6A2E1016: "w2h",
    0x01CB8011: "r16", 0xDB7DA00D: "r16", 0xB098300C: "r16", 0x0CB6800E: "u8x4",
}


def vertex_skin(v, enc):
    """-> list of (bone index, weight) with weight > 0."""
    posw = struct.unpack_from("<h", v, 6)[0]
    if enc == "w4":
        w0 = posw / 32767.0
        w1, w2 = struct.unpack_from("<2e", v, 24)
        ws = [w0, w1, w2, max(0.0, 1.0 - w0 - w1 - w2)]
        pairs = zip(v[16:20], ws)
    elif enc == "w2h":
        i0, i1 = struct.unpack_from("<2e", v, 20)
        w0 = posw / 32767.0
        pairs = [(int(i0), w0), (int(i1), 1.0 - w0)]
    elif enc == "r16":
        pairs = [(posw, 1.0)]
    elif enc == "u8x4":
        pairs = zip(v[8:12], [x / 255.0 for x in v[12:16]])
    else:
        return [(0, 1.0)]
    out = {}
    for i, w in pairs:
        if w > 1e-4:
            out[i] = out.get(i, 0.0) + w
    return list(out.items())


def read_bones(b):
    """-> list of dict(joint, parent, local(16 floats, row-major, translation in [12:15]), invbind)."""
    n = struct.unpack_from("<H", b, 6)[0]
    off = struct.unpack_from("<I", b, 0x24)[0]
    bones = []
    for i in range(n):
        joint, parent = b[off + i * 24], b[off + i * 24 + 1]
        local = struct.unpack_from("<16f", b, off + n * 24 + i * 64)
        inv = struct.unpack_from("<16f", b, off + n * 88 + i * 64)
        bones.append(dict(joint=joint, parent=parent, local=local, invbind=inv))
    remap = b[off + n * 152: off + n * 152 + 256] if n else b""
    return bones, remap


def read_model(b):
    if b[:4] != b"MOD\0":
        raise ValueError("not a MOD file")
    nbones, nmesh, nmat = struct.unpack_from("<HHH", b, 6)
    ntex = struct.unpack_from("<I", b, 0x1C)[0]
    tex_off, mesh_off, vb, ib = struct.unpack_from("<IIII", b, 0x2C)
    bmin = struct.unpack_from("<3f", b, 0x50)
    bmax = struct.unpack_from("<3f", b, 0x60)
    # skinned models: bone block = n*24 records, n local mats, n inverse-bind mats
    # (quantisation baked in: diagonal = cube size), 256-byte joint remap
    bone_off = struct.unpack_from("<I", b, 0x24)[0]
    qscale = None
    if nbones:
        qscale = struct.unpack_from("<f", b, bone_off + nbones * (24 + 64))[0]
    texs = [b[tex_off + i * 64:tex_off + i * 64 + 64].split(b"\0")[0].decode("latin-1") for i in range(ntex)]
    mat_off = tex_off + ntex * 64
    mats = [struct.unpack_from("<3I", b, mat_off + i * 160 + 12) for i in range(nmat)]
    meshes = []
    for k in range(nmesh):
        e = mesh_off + k * 48
        vc = struct.unpack_from("<H", b, e + 2)[0]
        bits = struct.unpack_from("<I", b, e + 4)[0]
        mat = (bits >> 12) & 0xFFF
        lod, stride = b[e + 8], b[e + 10]  # lod: really a render class (0x01 scenery, 0x21 characters)
        vstart, voff, fmt, istart, icount, vbase = struct.unpack_from("<IIIIII", b, e + 0x0C)
        meshes.append(dict(vc=vc, mat=mat, lod=lod, lodmask=bits >> 24, group=bits & 0xFFF, stride=stride, vstart=vstart, voff=voff,
                           fmt=fmt, istart=istart, icount=icount, vbase=vbase))
    return dict(bones=nbones, qscale=qscale, texs=texs, mats=mats, meshes=meshes, vb=vb, ib=ib, bmin=bmin, bmax=bmax)


def list_tris(idx):
    for j in range(0, len(idx) - 2, 3):
        t = idx[j:j + 3]
        if len(set(t)) == 3:
            yield tuple(t)


def mesh_geometry(b, m, M):
    pos_enc, uv_off = LAYOUTS.get(m["fmt"], (None, None))
    if pos_enc is None:
        return None
    idx = struct.unpack_from(f"<{m['icount']}H", b, M["ib"] + m["istart"] * 2)
    base = M["vb"] + m["voff"]
    # quantised into a cube anchored at bbox min; size from the inverse-bind
    # matrices, falling back to the largest bbox dimension for boneless models
    cube = M["qscale"] or max(M["bmax"][i] - M["bmin"][i] for i in range(3))
    verts, uvs = {}, {}
    for i in sorted(set(idx)):
        o = base + (m["vbase"] + i) * m["stride"]
        if pos_enc == "f32":
            p = struct.unpack_from("<3f", b, o)
        else:
            q = struct.unpack_from("<3h", b, o)
            p = tuple(M["bmin"][a] + q[a] / 32767.0 * cube for a in range(3))
        verts[i] = p
        if uv_off is not None:
            u, v = struct.unpack_from("<2e", b, o + uv_off)
            uvs[i] = (u, 1.0 - v)
    return verts, uvs, list(list_tris(idx))


def first_tree(b, M):
    """mesh index -> keep, for models that hold several copies of themselves under separate root bones (VS weapons:
    2-4 copies, one per mount): only the meshes skinned to the first root's tree. None when there is one tree."""
    bones = read_bones(b)[0]
    roots = [i for i, bn in enumerate(bones) if bn["parent"] == 255]
    if len(roots) < 2:
        return None

    def root(i):
        for _ in range(len(bones)):
            if bones[i]["parent"] == 255:
                return i
            i = bones[i]["parent"]
        return i
    keep = {}
    for k, m in enumerate(M["meshes"]):
        enc = SKIN.get(m["fmt"])
        if not enc or not m["icount"]:
            keep[k] = True
            continue
        i0 = struct.unpack_from("<H", b, M["ib"] + m["istart"] * 2)[0]
        o = M["vb"] + m["voff"] + (m["vbase"] + i0) * m["stride"]
        bi = max(vertex_skin(b[o:o + m["stride"]], enc), key=lambda x: x[1])[0]
        keep[k] = bi >= len(bones) or root(bi) == roots[0]
    return keep


def export(src, dst, motions=None, motion=0, one_copy=False):
    """motions: an rMotionList's bytes: skinned meshes take that motion's first frame (lp2pose), else the bind pose.
    one_copy: only the first copy of a model built as several (first_tree)."""
    b = open(src, "rb").read()
    M = read_model(b)
    mats = None
    if motions and M["bones"]:
        import lp2pose
        ms = lp2pose.motions(motions)
        if motion < len(ms) and ms[motion]:
            mats = lp2pose.skin_matrices(read_bones(b)[0], ms[motion])
    mtl = os.path.splitext(dst)[0] + ".mtl"
    out = [f"# {os.path.basename(src)}\nmtllib {os.path.basename(mtl)}\n"]
    nv = nt = skipped = 0
    keep = first_tree(b, M) if one_copy else None
    for k, m in enumerate(M["meshes"]):
        if keep is not None and not keep.get(k, True):
            continue
        g = mesh_geometry(b, m, M)
        if g is None:
            skipped += 1
            continue
        verts, uvs, tris = g
        if mats and m["fmt"] in SKIN:
            import lp2pose
            base = M["vb"] + m["voff"]
            for i, p in verts.items():
                o = base + (m["vbase"] + i) * m["stride"]
                verts[i] = lp2pose.pose_point(p, vertex_skin(b[o:o + m["stride"]], SKIN[m["fmt"]]), mats)
        remap, tmap = {}, {}
        out.append(f"o mesh{k:03d}_lod{m['lodmask']:02x}_fmt{m['fmt']:08x}\nusemtl mat{m['mat']:03d}\n")
        for i, p in verts.items():
            nv += 1
            remap[i] = nv
            out.append("v %.5f %.5f %.5f\n" % p)
            if uvs:
                nt += 1
                tmap[i] = nt
                out.append("vt %.6f %.6f\n" % uvs[i])
        for t in tris:
            if uvs:
                out.append("f %d/%d %d/%d %d/%d\n" % tuple(x for v in t for x in (remap[v], tmap[v])))
            else:
                out.append("f %d %d %d\n" % tuple(remap[v] for v in t))
    with open(dst, "w") as f:
        f.writelines(out)
    # texture names are archive paths; resolve against the extracted tree root
    root = find_tree_root(src)
    with open(mtl, "w") as f:
        for i, slots in enumerate(M["mats"]):
            f.write(f"newmtl mat{i:03d}\n")
            for slot, key in ((slots[0], "map_Kd"), (slots[1], "# normal")):
                if slot and slot <= len(M["texs"]):
                    rel = M["texs"][slot - 1].replace("\\", "/") + ".dds"
                    hit = (resolve_ci(root, rel) if root else None) or find_variant(src, rel)
                    f.write(f"{key} {os.path.relpath(hit, os.path.dirname(dst)) if hit else rel}\n")
    return M, skipped


def find_tree_root(src):
    """The extracted archive folder: parent of the first path part (scr/model/effect)."""
    parts = os.path.abspath(src).split(os.sep)
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower() in ("scr", "model", "effect"):
            return os.sep.join(parts[:i])
    return None


_DDS = None


def find_variant(src, rel):
    """Texture not in this archive: look for the same name, or another colour
    variant (_A/_B/_C...), anywhere in the extracted 'raw' tree."""
    global _DDS
    parts = os.path.abspath(src).split(os.sep)
    if "raw" not in parts:
        return None
    raw = os.sep.join(parts[:len(parts) - parts[::-1].index("raw")])
    if _DDS is None:
        _DDS = {}
        for d, _, fs in os.walk(raw):
            for f in fs:
                if f.endswith(".dds"):
                    _DDS.setdefault(f.lower(), os.path.join(d, f))
    name = os.path.basename(rel).lower()
    if name in _DDS:
        return _DDS[name]
    stem = name[:-4]
    if len(stem) > 2 and stem[-2] == "_":
        for c in "abcdefgh":
            hit = _DDS.get(f"{stem[:-1]}{c}.dds")
            if hit:
                return hit
    return None


def resolve_ci(root, rel):
    """case-insensitive, trying every spelling: an archive can hold both model\\ak\\... and Model\\Ak\\... (uVsD4),
    two folders here."""
    part, _, rest = rel.partition("/")
    try:
        names = [n for n in os.listdir(root) if n.lower() == part.lower()]
    except OSError:
        return None
    for n in names:
        hit = resolve_ci(os.path.join(root, n), rest) if rest else os.path.join(root, n)
        if hit:
            return hit
    return None


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "-r":
        ok = bad = 0
        for d, _, fs in os.walk(a[1]):
            for fn in fs:
                if fn.endswith(".rModel"):
                    p = os.path.join(d, fn)
                    try:
                        export(p, p[: -len(".rModel")] + ".obj"); ok += 1
                    except Exception as e:
                        bad += 1; print(f"{p}: {e}", file=sys.stderr)
        print(f"exported {ok}, failed {bad}")
    else:
        pose = None
        if "--pose" in a:  # --pose MOTIONS.rMotionList[:N]
            k = a.index("--pose")
            path, _, n = a[k + 1].partition(":")
            pose = (open(path, "rb").read(), int(n or 0))
            del a[k:k + 2]
        one = "--one-copy" in a
        a = [x for x in a if x != "--one-copy"]
        M, skipped = export(a[0], a[1] if len(a) > 1 else os.path.splitext(a[0])[0] + ".obj", *(pose or (None, 0)), one_copy=one)
        print(f"bones {M['bones']} meshes {len(M['meshes'])} materials {len(M['mats'])} skipped {skipped}")


if __name__ == "__main__":
    main()
