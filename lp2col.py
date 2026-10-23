#!/usr/bin/env python3
"""Lost Planet 1 (PC) collision 'SBC1' -> Lost Planet 2 rCollision 'SBC\\xff', with its BVH.

  lp2col.py LP1.sbc1 TEMPLATE.rCollision OUT.rCollision

LP1 (little-endian on PC, big-endian on Xbox 360; nativePC ZZPack2/sNNN.arc scr\\stageN\\sNNN\\atari/tamasNNN):
  0x00 'SBC1' u32 file size, u16 6, u16 groups, u16 groups - 1, u16 ?, u32 offsets: groups, triangles,
       surfaces ?, vertices; 0x20 u32 tris - 1, tris, groups, vertices; 0x30 bounds ?; 0x50 a BVH (unused)
  groups x 24: u32 0, u32 first triangle, u32 ?, u32 first vertex, u32 index, u32 ?
  triangles x 48: 16 B runtime, u16 v0 v1 v2 (relative to the group's first vertex), 6 B, u32 surface
       flags (0x3fffff00 plain, 0x8000xxxx material bits), 16 B 0
  vertices x 16: f32 xyz, 0 (cm, the same stage space as LP2)
LP2 (sbc.py has the reader):
  0x00 'SBC\\xff' u32 2009052600, u16 groups, u16 surfaces, u32 triangles, u32 vertices, 12 B 0
  0x20 vec4 min, vec4 max; groups x 48: vec4 min, vec4 max, u32 0 (runtime), u32 first triangle,
       u32 first vertex, u32 -1
  triangles x 32: f32 normal xyz, u16 v0 v1 v2 (group-relative), u16 surface, 12 B 0
  vertices x 16: f32 xyz, 0;  surfaces x 32: u32 flags, then the template's 28 bytes
  BVHC chunks, one per group (leaves = group-relative triangle ids) and a last one over the groups
  (leaves = group ids): 'BVHC' u32 2008120100, u32 1, u32 0, vec4 min, vec4 max, u32 nodes,
  u32 leaves, 8 B 0, u16 leaf order, then nodes x 112 (pre-order, root first):
    u8 x4 mask (the same byte four times: bit 4+i = slot i is a leaf, bit i = slot i is a node),
    u16 x4 child (node index or leaf id), u32 0, f32 x4 each: min x, min y, min z, max x, max y, max z
Surfaces: LP1 0x3fffff00 -> the template's plain surface (no 0x40000000 bit: 0x19f8f6ff atari, 0x19f68bff
tama); 0x8000xxxx -> 0x4000xxxx (s900 -> online00: 0x40001000/2000/80000 all exist in the stock table).
"""
import struct, sys

LP2_VERSION = 2009052600
BVHC_VERSION = 2008120100
EMPTY = (3e38, 3e38, 3e38, -3e38, -3e38, -3e38)


def read_sbc1(b):
    if b[:4] != b"SBC1":
        raise ValueError("not an LP1 SBC1 collision file")
    E = "<" if b[8] == 6 else ">"  # u16 6: PC little-endian, Xbox 360 (Colonies maps) big-endian
    ng = struct.unpack_from(E + "H", b, 10)[0]
    og, ot, os_, ov = struct.unpack_from(E + "4I", b, 0x10)
    ntri, nv = (os_ - ot) // 48, (len(b) - ov) // 16
    grp = [struct.unpack_from(E + "6I", b, og + 24 * i) for i in range(ng)]
    verts = [struct.unpack_from(E + "3f", b, ov + 16 * i) for i in range(nv)]
    groups = []
    for gi, g in enumerate(grp):
        t1 = grp[gi + 1][1] if gi + 1 < ng else ntri
        v1 = grp[gi + 1][3] if gi + 1 < ng else nv
        tris = []
        for t in range(g[1], t1):
            o = ot + 48 * t
            tris.append((struct.unpack_from(E + "3H", b, o + 16), struct.unpack_from(E + "I", b, o + 0x1C)[0]))
        groups.append(dict(verts=verts[g[3]:v1], tris=tris))
    return groups


def write_sbc1(groups, flags=0x3FFFFF00):
    """groups [dict(verts [(x, y, z)], tris [((a, b, c), surface)])] -> LP1 SBC1 (PC, little-endian) as read_sbc1
    reads it (no surface table or BVH: nothing here uses them). A group holds at most 65535 vertices."""
    ng = len(groups)
    ntri = sum(len(g["tris"]) for g in groups)
    nv = sum(len(g["verts"]) for g in groups)
    og = 0x50
    ot = og + 24 * ng
    ov = ot + 48 * ntri
    grp, tri, vert = bytearray(), bytearray(), bytearray()
    t0 = v0 = 0
    for i, g in enumerate(groups):
        assert len(g["verts"]) <= 65535
        grp += struct.pack("<6I", 0, t0, 0, v0, i, 0)
        for (a, b, c), _surface in g["tris"]:
            tri += bytes(16) + struct.pack("<3H6xI16x", a, b, c, flags)
        for v in g["verts"]:
            vert += struct.pack("<3fI", *v, 0)
        t0 += len(g["tris"])
        v0 += len(g["verts"])
    size = ov + len(vert)
    head = struct.pack("<4sIHHHH4I4I", b"SBC1", size, 6, ng, max(0, ng - 1), 0, og, ot, ov, ov,
                       max(0, ntri - 1), ntri, ng, nv)
    return head.ljust(og, b"\0") + grp + tri + vert


def bounds(points):
    xs, ys, zs = zip(*points)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def union(bs):
    return (min(b[0] for b in bs), min(b[1] for b in bs), min(b[2] for b in bs),
            max(b[3] for b in bs), max(b[4] for b in bs), max(b[5] for b in bs))


def bvh(items):
    """items: [(leaf id, box)] -> (nodes [(mask, children, boxes)], leaf order). 4-wide, pre-order."""
    nodes, order = [], []

    def split(its, parts):
        if parts == 1 or len(its) <= 1:
            return [its]
        box = union([b for _, b in its])
        axis = max(range(3), key=lambda a: box[a + 3] - box[a])
        its = sorted(its, key=lambda it: it[1][axis] + it[1][axis + 3])
        h = len(its) // 2
        return split(its[:h], parts // 2) + split(its[h:], parts // 2)

    def build(its):
        idx = len(nodes)
        nodes.append(None)
        groups = [[it] for it in its] if len(its) <= 4 else [g for g in split(its, 4) if g]
        mask, children, boxes = 0, [0] * 4, [EMPTY] * 4
        for slot, g in enumerate(groups):
            if len(g) == 1:
                mask |= 0x10 << slot
                children[slot] = g[0][0]
                order.append(g[0][0])
            else:
                mask |= 1 << slot
                children[slot] = build(g)
            boxes[slot] = union([b for _, b in g])
        nodes[idx] = (mask, children, boxes)
        return idx

    build(items)
    if len(nodes) > 0xFFFF:
        raise ValueError("BVH over 65535 nodes: split the group")
    return nodes, order


def bvhc(items):
    nodes, order = bvh(items)
    box = union([b for _, b in items])
    out = bytearray(struct.pack("<4sIII4f4fIIII", b"BVHC", BVHC_VERSION, 1, 0, *box[:3], 0.0, *box[3:], 0.0,
                                len(nodes), len(items), 0, 0))
    out += struct.pack(f"<{len(order)}H", *order)
    for mask, children, boxes in nodes:
        out += bytes([mask] * 4) + struct.pack("<4HI", *children, 0)
        for k in range(6):
            out += struct.pack("<4f", *(bx[k] for bx in boxes))
    return bytes(out)


def write_lp2(groups, template):
    if template[:4] != b"SBC\xff":
        raise ValueError("template is not an LP2 rCollision")
    tng, tns, tnt, tnv = struct.unpack_from("<HHII", template, 8)
    so = 0x40 + 48 * tng + 32 * tnt + 16 * tnv
    tsurf = [template[so + 32 * i:so + 32 * i + 32] for i in range(tns)]
    tflags = [struct.unpack_from("<I", t)[0] for t in tsurf]
    plain = next((f for f in tflags if not f & 0xC0000000), tflags[0])  # 0x19f8f6ff (atari), 0x19f68bff (tama)
    surf_flags, surf_index = [], {}

    def surface(f):
        lp2 = plain if f == 0x3FFFFF00 else (f & 0x3FFFFFFF) | 0x40000000
        if lp2 not in surf_index:
            surf_index[lp2] = len(surf_flags)
            surf_flags.append(lp2)
        return surf_index[lp2]

    groups = [g for g in groups if g["tris"]]
    head, tris, verts, chunks, gboxes = [], bytearray(), bytearray(), [], []
    nt = nv = 0
    for g in groups:
        if len(g["verts"]) > 0xFFFF or len(g["tris"]) > 0xFFFF:
            raise ValueError("group over 65535 vertices or triangles")
        gb = bounds(g["verts"])
        gboxes.append(gb)
        head.append(struct.pack("<4f4fIIIi", *gb[:3], 0.0, *gb[3:], 0.0, 0, nt, nv, -1))
        items = []
        for k, ((a, b_, c), f) in enumerate(g["tris"]):
            p = [g["verts"][i] for i in (a, b_, c)]
            e1 = [p[1][i] - p[0][i] for i in range(3)]
            e2 = [p[2][i] - p[0][i] for i in range(3)]
            n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            ln = sum(x * x for x in n) ** 0.5 or 1.0
            tris += struct.pack("<3f4H12x", *(x / ln for x in n), a, b_, c, surface(f))
            items.append((k, bounds(p)))
        for v in g["verts"]:
            verts += struct.pack("<4f", *v, 0.0)
        chunks.append(bvhc(items))
        nt += len(g["tris"])
        nv += len(g["verts"])
    chunks.append(bvhc(list(enumerate(gboxes))))
    if len(surf_flags) > 0xFFFF:
        raise ValueError("too many surface types")
    allb = union(gboxes)
    out = bytearray(struct.pack("<4sIHHII12x", b"SBC\xff", LP2_VERSION, len(groups), len(surf_flags), nt, nv))
    out += struct.pack("<4f4f", *allb[:3], 0.0, *allb[3:], 0.0)
    out += b"".join(head) + tris + verts
    for f in surf_flags:
        out += struct.pack("<I", f) + tsurf[tflags.index(f) if f in tflags else 0][4:]
    out += b"".join(chunks)
    return bytes(out), surf_flags


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    groups = read_sbc1(open(sys.argv[1], "rb").read())
    out, surf = write_lp2(groups, open(sys.argv[2], "rb").read())
    open(sys.argv[3], "wb").write(out)
    print(f"{sys.argv[3]}: {len(groups)} groups, {sum(len(g['tris']) for g in groups)} triangles, "
          f"surfaces {', '.join(f'{s:#010x}' for s in surf)}, {len(out)} bytes")


if __name__ == "__main__":
    main()
