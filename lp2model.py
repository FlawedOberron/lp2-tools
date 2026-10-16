"""Lost Planet 2 rModel writer (MT 'MOD\\0' v0xC5, character parts).

Builds a skinned part model from neutral data (positions in LP2 space: cm, Y-up) on top of a
template rModel of the same slot, which supplies what we do not author yet: the standard
skeleton (joint records and bind matrices), the material and texture blocks, the per-format
render bytes and the header's LOD distances. Layout notes are in mod2obj.py; write-side facts:

  file    header 0x80 | bones n*24 + n*64 local + n*64 invbind + 256 joint->index remap
          | groups 32B (u32 id, 12 pad, sphere xyzr) | textures 64B | materials 160B
          | meshes 48B | u32 N + N*144B bounds | vertex buffer | u16 triangle list
  header  0x0C vertex count, 0x10 index count, 0x14 triangle count, 0x18 VB size,
          0x1C textures, 0x20 groups, 0x24.. section offsets, 0x40 sphere, 0x50/0x60 bbox,
          0x70 16 bytes from the template (LOD distances 1000/3000, 3)
  bone    u8 joint, u8 parent index (255 root), u8 mirror index (self when none), 0,
          f32 radius, f32 distance to parent, f32 xyz local offset;
          invbind = Q * W^-1 (row vectors; Q = diag(S) with bbox min as translation)
  mesh    +0 0xFFFF, +2 u16 vertex count, +4 u32 group | material << 12 | LOD mask << 24,
          +8 render class, 0, stride, 3, +0x0C first vertex, +0x10 run byte offset,
          +0x14 format, +0x18 first index, +0x1C index count, +0x20 0, +0x24 u8 bound
          count, 0, +0x26 u16 draw order (1..N), +0x28 u16 min/max vertex index, +0x2C 0
  bounds  per mesh, per bone with weight (ascending): u32 bone index, 12 pad, sphere,
          aabb min, aabb max (w 0), 4x4 identity with the centre as translation,
          half extents - all in the bone's local space
"""
import math, struct

FMT_SKIN = 0x14D40019    # 28 bytes: pos i16x3, w0 i16, normal u8x4, tangent u8x4, idx u8x4, uv f16x2, w1 w2 f16
FMT_SHADOW = 0x0CB6800E  # 20 bytes: pos i16x3, 0, idx u8x4, weights u8x4, normal u8x4 (untextured material)
STRIDE = {FMT_SKIN: 28, FMT_SHADOW: 20}
LOD_ALL = 0xFF
MAX_RUN_VERTS = 0xFFFF
MIN_WEIGHT = 0.002       # smaller influences are dropped (quantisation noise, stray paint)

KNOWN_SAFE_BONES = 31   # most bones in any shipped model (bd2902)
MAX_CUSTOM_BONES = 100


class ExportError(Exception):
    pass


# ---------------------------------------------------------------- 4x4 (row-major, row vectors: world = local * parent)

def mmul(a, b):
    return tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4))


def minv(m):
    a = [list(m[r * 4:r * 4 + 4]) + [1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for c in range(4):
        p = max(range(c, 4), key=lambda r: abs(a[r][c]))
        a[c], a[p] = a[p], a[c]
        d = a[c][c]
        a[c] = [x / d for x in a[c]]
        for r in range(4):
            if r != c:
                f = a[r][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return tuple(a[r][4 + c] for r in range(4) for c in range(4))


def translation(t):
    return (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1)


def xform(p, m):
    return tuple(p[0] * m[c] + p[1] * m[4 + c] + p[2] * m[8 + c] + m[12 + c] for c in range(3))


# ---------------------------------------------------------------- template

def read_template(b):
    if b[:4] != b"MOD\0":
        raise ExportError("template is not an rModel")
    nb, nm, nmat = struct.unpack_from("<HHH", b, 6)
    ntex = struct.unpack_from("<I", b, 0x1C)[0]
    o_bones, o_grp, o_tex, o_mesh = struct.unpack_from("<4I", b, 0x24)
    bones = []
    for i in range(nb):
        r = o_bones + i * 24
        joint, parent, mirror = b[r], b[r + 1], b[r + 2]
        radius = struct.unpack_from("<f", b, r + 4)[0]
        local = struct.unpack_from("<16f", b, o_bones + nb * 24 + i * 64)
        bones.append(dict(joint=joint, parent=parent, mirror=mirror, radius=radius, local=local))
    for bn in bones:  # some bones carry rotations (j100, chain roots), so full matrices
        bn["wm"] = bn["local"] if bn["parent"] == 255 else mmul(bn["local"], bones[bn["parent"]]["wm"])
        bn["world"] = tuple(bn["wm"][12:15])
    render = {}
    for k in range(nm):
        e = o_mesh + k * 48
        fmt = struct.unpack_from("<I", b, e + 0x14)[0]
        render.setdefault(fmt, b[e + 8:e + 12])
    mats = []
    for i in range(nmat):
        raw = b[o_tex + ntex * 64 + i * 160:][:160]
        mats.append(dict(raw=raw, slots=struct.unpack_from("<3I", raw, 12)))
    return dict(version=struct.unpack_from("<H", b, 4)[0], bones=bones, render=render, mats=mats,
                tex_block=b[o_tex:o_tex + ntex * 64], ntex=ntex, mat_block=b[o_tex + ntex * 64:o_mesh],
                lod_block=b[0x70:0x80])


def shadow_material(tpl):
    """Index of the template's untextured material (the one the 20-byte meshes use)."""
    for i, m in enumerate(tpl["mats"]):
        if m["slots"] == (0, 0, 0):
            return i
    return None


# ---------------------------------------------------------------- encoding helpers

def _u8n(x):
    return max(0, min(255, int(round(x * 127.0 + 127.0))))


def _q16(x):
    return max(0, min(32767, int(round(x * 32767.0))))


def _sphere(points):
    lo = [min(p[a] for p in points) for a in range(3)]
    hi = [max(p[a] for p in points) for a in range(3)]
    c = [(lo[a] + hi[a]) * 0.5 for a in range(3)]
    r = max(math.dist(c, p) for p in points)
    return lo, hi, c, r


def _top4(weights):
    """[(bone index, w)] -> exactly 4 pairs, strongest first, normalised."""
    ws = sorted(((i, w) for i, w in weights if w > MIN_WEIGHT), key=lambda t: -t[1])[:4]
    s = sum(w for _, w in ws)
    if s <= 0:
        raise ExportError("vertex without weights")
    ws = [(i, w / s) for i, w in ws]
    while len(ws) < 4:
        ws.append((0, 0.0))
    return ws


def encode_skin_vertex(q, n, t, uv, ws):
    w0 = _q16(ws[0][1])
    w1 = struct.unpack("<e", struct.pack("<e", ws[1][1]))[0]
    w2 = struct.unpack("<e", struct.pack("<e", ws[2][1]))[0]
    return struct.pack("<3hh4B4B4B2e2e", q[0], q[1], q[2], w0,
                       _u8n(n[0]), _u8n(n[1]), _u8n(n[2]), 0x7F,
                       _u8n(t[0]), _u8n(t[1]), _u8n(t[2]), 0xFF if t[3] >= 0 else 0x00,
                       ws[0][0], ws[1][0], ws[2][0], ws[3][0],
                       uv[0], 1.0 - uv[1], w1, w2)


def encode_shadow_vertex(q, n, ws):
    raw = [int(round(w * 255)) for _, w in ws]
    raw[0] += 255 - sum(raw)
    return struct.pack("<3hh4B4B4B", q[0], q[1], q[2], 0,
                       ws[0][0], ws[1][0], ws[2][0], ws[3][0], *raw,
                       _u8n(n[0]), _u8n(n[1]), _u8n(n[2]), 0xFF)


def decode_weights(ws):
    """The weights as the game will read them back (w0 i16, w1/w2 f16, w3 = rest)."""
    w0 = _q16(ws[0][1]) / 32767.0
    w1 = struct.unpack("<e", struct.pack("<e", ws[1][1]))[0]
    w2 = struct.unpack("<e", struct.pack("<e", ws[2][1]))[0]
    return [w0, w1, w2, max(0.0, 1.0 - w0 - w1 - w2)]


# ---------------------------------------------------------------- build

def build_model(tpl, custom_bones, meshes, shadow=True):
    """tpl: read_template(); custom_bones: [dict(joint, parent (joint id), world xyz cm)];
    meshes: [dict(group, mat, lodmask, verts=[dict(pos, normal, tangent xyzw, uv, weights
    [(joint id, w)])], tris=[(a, b, c)])]. Returns (bytes, report dict)."""
    # skeleton: template bones in their order, then custom bones parents-first
    bones = [dict(b) for b in tpl["bones"]]
    index = {b["joint"]: i for i, b in enumerate(bones)}
    pending = list(custom_bones)
    while pending:
        ready = [c for c in pending if c["parent"] in index]
        if not ready:
            raise ExportError("custom bones not connected to the skeleton: "
                              + ", ".join(str(c.get("name", c["joint"])) for c in pending))
        for c in ready:
            if c["joint"] in index:
                raise ExportError(f"joint id {c['joint']} used twice")
            p = index[c["parent"]]
            wm = translation(c["world"])
            local = mmul(wm, minv(bones[p]["wm"]))
            index[c["joint"]] = len(bones)
            bones.append(dict(joint=c["joint"], parent=p, mirror=len(bones), radius=0.0,
                              local=local, wm=wm, world=tuple(c["world"])))
            pending.remove(c)
    if len(bones) > 255:
        raise ExportError("more than 255 bones")
    for b in bones:
        b["dist"] = math.hypot(*b["local"][12:15]) if b["parent"] != 255 else 0.0
        b["inv"] = minv(b["wm"])

    # every mesh, plus a shadow copy when the template has the untextured material
    shadow_mat = shadow_material(tpl) if shadow else None
    work = []
    for m in meshes:
        verts = []
        for v in m["verts"]:
            try:
                ws = _top4([(index[j], w) for j, w in v["weights"]])
            except KeyError as e:
                raise ExportError(f"weight on joint {e.args[0]} that this part's skeleton lacks")
            verts.append((v, ws))
        work.append(dict(fmt=FMT_SKIN, group=m["group"], mat=m["mat"], lod=m.get("lodmask", LOD_ALL),
                         verts=verts, tris=m["tris"]))
    if shadow_mat is not None:
        for m in list(work):
            work.append(dict(m, fmt=FMT_SHADOW, mat=shadow_mat))

    # quantisation cube from all positions
    allp = [v["pos"] for m in work for v, _ in m["verts"]]
    if not allp:
        raise ExportError("nothing to export")
    lo, hi, centre, radius = _sphere(allp)
    S = max(hi[a] - lo[a] for a in range(3)) or 1.0

    def quant(p):
        return tuple(_q16((p[a] - lo[a]) / S) for a in range(3))

    # vertex runs per stride (indices are relative to the run start, u16)
    vb, ib, entries, bounds = bytearray(), [], [], []
    run = {}  # fmt -> [byte offset, vertex count]
    for k, m in enumerate(work):
        n = len(m["verts"])
        if n > MAX_RUN_VERTS:
            raise ExportError(f"a mesh piece has {n} vertices (max {MAX_RUN_VERTS}); split it")
        r = run.get(m["fmt"])
        if r is None or r[1] + n > MAX_RUN_VERTS or entries and entries[-1]["fmt"] != m["fmt"]:
            r = run[m["fmt"]] = [len(vb), 0]
        first = r[1]
        for v, ws in m["verts"]:
            q = quant(v["pos"])
            if m["fmt"] == FMT_SKIN:
                vb += encode_skin_vertex(q, v["normal"], v["tangent"], v["uv"], ws)
            else:
                vb += encode_shadow_vertex(q, v["normal"], ws)
        r[1] += n
        istart = len(ib)
        for t in m["tris"]:
            ib.extend(first + i for i in t)
        # bounds: bones that carry weight, in their local (translation-only) space
        per = {}
        for v, ws in m["verts"]:
            for (bi, wn), w in zip(ws, decode_weights(ws)):
                if wn > 0 and w > 1e-6:  # padding slots read back as tiny w3 noise
                    per.setdefault(bi, []).append(v["pos"])
        recs = []
        for bi in sorted(per):
            inv = bones[bi]["inv"]
            pts = [xform(p, inv) for p in per[bi]]
            blo, bhi, bc, br = _sphere(pts)
            ext = [(bhi[a] - blo[a]) * 0.5 for a in range(3)]
            recs.append(struct.pack("<I12x4f4f4f16f4f", bi, *bc, br, *blo, 0.0, *bhi, 0.0,
                                    1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, bc[0], bc[1], bc[2], 1,
                                    *ext, 0.0))
        if len(recs) > 255:
            raise ExportError("a mesh piece uses more than 255 bones")
        bounds += recs
        entries.append(dict(fmt=m["fmt"], vc=n, bits=(m["group"] & 0xFFF) | ((m["mat"] & 0xFFF) << 12)
                            | ((m["lod"] & 0xFF) << 24), vstart=first, voff=r[0], istart=istart,
                            icount=len(m["tris"]) * 3, nbounds=len(recs), order=k + 1))
    if len(ib) and max(ib) > 0xFFFF:
        raise ExportError("index out of range")

    # groups: model-space sphere of each group's vertices
    gpts = {}
    for m in work:
        gpts.setdefault(m["group"], []).extend(v["pos"] for v, _ in m["verts"])
    groups = []
    for g in sorted(gpts):
        _, _, gc, gr = _sphere(gpts[g])
        groups.append(struct.pack("<I12x4f", g, *gc, gr))

    # sections
    nb = len(bones)
    bone_blk = bytearray()
    for i, b in enumerate(bones):
        bone_blk += struct.pack("<4B5f", b["joint"], b["parent"], b["mirror"], 0, b["radius"], b["dist"],
                                *b["local"][12:15])
    for b in bones:
        bone_blk += struct.pack("<16f", *b["local"])
    Q = (S, 0, 0, 0, 0, S, 0, 0, 0, 0, S, 0, lo[0], lo[1], lo[2], 1)
    for b in bones:
        bone_blk += struct.pack("<16f", *mmul(Q, b["inv"]))
    remap = bytearray(b"\xff" * 256)
    for i, b in enumerate(bones):
        remap[b["joint"]] = i
    bone_blk += remap

    tex_mat = tpl["tex_block"] + tpl["mat_block"]
    nmat = len(tpl["mats"])
    mesh_blk = bytearray()
    for e in entries:
        lo_i, hi_i = e["vstart"], e["vstart"] + e["vc"] - 1
        mesh_blk += struct.pack("<HHI4sIIIIII BBH HHI", 0xFFFF, e["vc"], e["bits"],
                                tpl["render"].get(e["fmt"], bytes((0x21, 0, STRIDE[e["fmt"]], 3))),
                                e["vstart"], e["voff"], e["fmt"], e["istart"], e["icount"], 0,
                                e["nbounds"], 0, e["order"], lo_i, hi_i, 0)
    bound_blk = struct.pack("<I", len(bounds)) + b"".join(bounds)

    o_bones = 0x80
    o_grp = o_bones + len(bone_blk)
    o_tex = o_grp + 32 * len(groups)
    o_mesh = o_tex + len(tex_mat)
    o_vb = o_mesh + len(mesh_blk) + len(bound_blk)
    o_ib = o_vb + len(vb)
    hdr = bytearray(0x80)
    struct.pack_into("<4sHHHH", hdr, 0, b"MOD\0", tpl["version"], nb, len(entries), nmat)
    struct.pack_into("<6I", hdr, 0x0C, sum(e["vc"] for e in entries), len(ib), len(ib) // 3,
                     len(vb), tpl["ntex"], len(groups))
    struct.pack_into("<6I", hdr, 0x24, o_bones, o_grp, o_tex, o_mesh, o_vb, o_ib)
    struct.pack_into("<4f4f4f", hdr, 0x40, *centre, radius, *lo, 0.0, *hi, 0.0)
    hdr[0x70:0x80] = tpl["lod_block"]
    out = bytes(hdr) + bytes(bone_blk) + b"".join(groups) + tex_mat + bytes(mesh_blk) + bound_blk + bytes(vb) \
        + struct.pack(f"<{len(ib)}H", *ib)

    custom = nb - len(tpl["bones"])
    warnings = []
    if custom > MAX_CUSTOM_BONES:
        raise ExportError(f"{custom} custom bones (cap {MAX_CUSTOM_BONES})")
    if nb > KNOWN_SAFE_BONES:
        warnings.append(f"{nb} bones: no shipped model has more than {KNOWN_SAFE_BONES}; "
                        "the game's skinning may not cope (untested)")
    report = dict(bones=nb, custom_bones=custom, meshes=len(entries), vertices=sum(e["vc"] for e in entries),
                  triangles=len(ib) // 3, bytes=len(out), warnings=warnings,
                  joints={b["joint"]: i for i, b in enumerate(bones)})
    return out, report
