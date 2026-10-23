#!/usr/bin/env python3
"""Lost Planet 1 (PC or Xbox 360) map physics (Havok 4 packfile) -> Lost Planet 2 rHkCollision (Havok 6.6 packfile).

  lp2havok.py [--rebuild] LP1_HAV.bin LP2_TEMPLATE.rHkCollision OUT.rHkCollision

--rebuild writes a new MOPP tree (lp2mopp.py) in place of LP1's.

Both games' map physics (havokdata\\havNNN: grenades, debris, ragdolls) are one fixed rigid body with
hkMoppBvTreeShape -> hkSimpleMeshShape + hkMoppCode, in metres, Y up, the stage's space. The LP2 template
(a stock map's file) keeps every object; only the mesh and the MOPP change:
  hkpMoppCode (LP2 +0x10 vec4 info: offset xyz, scale; +0x20 hkArray<u8> data, +0x2C u8 build type; data
    inline from +0x30) <- LP1 hkMoppCode (the same info at +0x10, array at +0x20, data from +0x30).
    MOPP bytecode is assumed unchanged between Havok 4 and 6.6 (both start 28 00 ff 27 ...); its leaves are
    triangle indices, which stay in LP1's order. Build type -> 2 (not set).
  hkpSimpleMeshShape (+0x18 vertices hkArray<vec4>, +0x24 triangles hkArray<{i32 a, b, c; u16 welding}> 16 B,
    data from +0x50) <- LP1 hkSimpleMeshShape (+0x10 vertices, +0x1C triangles of 3 x i32, data from +0x40);
    welding info 0 (the template's welding type is NONE).
The data section is rebuilt (objects, then local / global / virtual fixups, 0xff-padded to 16) and its
section header updated; the data section must be the file's last (true for the stock files).
"""
import struct, sys
import hkpack


def obj(p, cls):
    return next(o for o, c in p["objects"] if c == cls)


def arr(b, at, E="<"):
    return struct.unpack_from(E + "I", b, at + 4)[0]  # hkArray: ptr, size, capacity | flags


def pad16(x, fill=b"\0"):
    return x + fill * (-len(x) % 16)


def read(b):
    """an LP1 (v2) or LP2 (v7) physics file -> (vertices [(x, y, z)], triangles [(a, b, c)], MOPP info, code)"""
    p = hkpack.read(b)
    E, d = p["E"], p["data"]["start"]  # Colonies maps only exist as Xbox 360 (big-endian) files
    if p["version"] == 2:
        m = d + obj(p, "hkSimpleMeshShape")
        nv, nt, vo, ts = arr(b, m + 0x10, E), arr(b, m + 0x1C, E), m + 0x40, 12
        c = d + obj(p, "hkMoppCode")
    else:
        m = d + obj(p, "hkpSimpleMeshShape")
        nv, nt, vo, ts = arr(b, m + 0x18, E), arr(b, m + 0x24, E), m + 0x50, 16
        c = d + obj(p, "hkpMoppCode")
    verts = [struct.unpack_from(E + "3f", b, vo + 16 * i) for i in range(nv)]
    tris = [struct.unpack_from(E + "3i", b, vo + 16 * nv + ts * i) for i in range(nt)]
    info = struct.unpack_from(E + "4f", b, c + 0x10)
    code = bytes(b[c + 0x30:c + 0x30 + arr(b, c + 0x20, E)])
    if tris and max(max(x) for x in tris) >= nv:
        raise SystemExit("triangle index out of range: layout guess is wrong")
    return verts, tris, info, code


def write(t, verts, tris, info, code):
    """the LP2 template file t with this mesh and MOPP -> bytes"""
    pt = hkpack.read(t)
    if pt["version"] < 6:
        raise SystemExit("expected an LP2 (v7) template")
    dt = pt["data"]["start"]
    objs_t = [c for _, c in pt["objects"]]
    if objs_t[-2:] != ["hkpMoppCode", "hkpSimpleMeshShape"]:
        raise SystemExit(f"template objects end with {objs_t[-2:]}, expected MOPP code then the mesh")
    nv, nt = len(verts), len(tris)
    vbytes = b"".join(struct.pack("<4f", *v[:3], 0) for v in verts)

    # template objects up to the MOPP code stay as they are (the BV tree's code info copy is 0 in the
    # stock files: filled in at load)
    code_at = obj(pt, "hkpMoppCode")
    head = bytes(t[dt:dt + code_at])
    # MOPP code object
    cobj = bytearray(t[dt + code_at:dt + code_at + 0x30])
    cobj[0x10:0x20] = struct.pack("<4f", *info)
    struct.pack_into("<II", cobj, 0x24, len(code), len(code) | 0xC0000000)
    cobj[0x2C] = 2
    mopp = pad16(bytes(cobj) + code)
    mesh_at = code_at + len(mopp)
    # mesh object
    mt = obj(pt, "hkpSimpleMeshShape")
    mobj = bytearray(t[dt + mt:dt + mt + 0x50])
    struct.pack_into("<II", mobj, 0x1C, nv, nv | 0xC0000000)
    struct.pack_into("<II", mobj, 0x28, nt, nt | 0xC0000000)
    tri_bytes = b"".join(struct.pack("<3iH2x", *x, 0) for x in tris)
    mesh = bytes(mobj) + vbytes + tri_bytes
    data = pad16(bytes(head) + mopp + mesh)

    # fixups: template ones before the MOPP code keep their offsets; the code / mesh ones move
    sec = pt["data"]
    locals_ = [(s, d) for s, d in sec["locals"] if s < code_at]
    locals_ += [(code_at + 0x20, code_at + 0x30), (mesh_at + 0x18, mesh_at + 0x50), (mesh_at + 0x24, mesh_at + 0x50 + 16 * nv)]
    globals_ = [(s, ds, mesh_at if (ds == 2 and d == mt) else d) for s, ds, d in sec["globals"]]
    virt = []
    for s, cs, co in sec["virtuals"]:
        virt.append((mesh_at if s == mt else s, cs, co))
    lf = pad16(b"".join(struct.pack("<2I", *x) for x in locals_), b"\xff")
    gf = pad16(b"".join(struct.pack("<3I", *x) for x in globals_), b"\xff")
    vf = pad16(b"".join(struct.pack("<3I", *x) for x in virt), b"\xff")
    body = data + lf + gf + vf
    o_lf = len(data)
    o_gf, o_vf = o_lf + len(lf), o_lf + len(lf) + len(gf)
    end = len(body)

    out = bytearray(t[:dt]) + body
    idx = [s["tag"] for s in pt["sections"]].index("__data__")
    h = 0x40 + idx * 0x30 + 20
    struct.pack_into("<7I", out, h, dt, o_lf, o_gf, o_vf, end, end, end)
    hkpack.read(bytes(out))  # self-check: it reads back
    return bytes(out)


def main():
    args = [a for a in sys.argv[1:] if a != "--rebuild"]
    if len(args) != 3:
        raise SystemExit(__doc__)
    verts, tris, info, code = read(open(args[0], "rb").read())
    if "--rebuild" in sys.argv:
        import lp2mopp
        info, code = lp2mopp.build(verts, tris)
    out = write(open(args[1], "rb").read(), verts, tris, info, code)
    open(args[2], "wb").write(out)
    print(f"{args[2]}: {len(verts)} vertices, {len(tris)} triangles, MOPP {len(code)} bytes, {len(out)} bytes")


if __name__ == "__main__":
    main()
