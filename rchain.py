#!/usr/bin/env python3
"""Lost Planet 2 rChain (MT 'CHN\\0' v0x0618): secondary-motion bone chains (scarves, straps).
  rchain.py FILE...        dump
Layout (reconstructed from the stock parts, unverified fields marked ?):
  0x00 'CHN\\0', u16 0x0618 version, u16 8 ?, u32 data size (file - 16), u32 chain count
  0x10 chains, 32 B each: u8 node count, u8 ? (1), u16 0, u32 offset of its first node
       (relative to this record), 8 B 0, 3 floats ? (1,1,1), u32 0
  nodes, 96 B each: u32 type (3 first, 2 others ?), u16 joint, u16 ? (1), 8 B 0,
       +0x10 3 floats min angle (rad), +0x1C float ?, +0x20 3 floats max angle, +0x2C float ?,
       +0x30 float ?, +0x34 u8 ?, u8 ?, u16 0, +0x38 float ?, +0x3C float ?,
       +0x40 u16 linked joint, +0x44 8 B 0, +0x4C float ?, +0x50 16 B 0
  then u32 0 and 0xCD padding to 16 bytes.
"""
import struct, sys


def parse(b):
    if b[:4] != b"CHN\0":
        raise ValueError("not an rChain")
    ver, unk, size, n = struct.unpack_from("<HHII", b, 4)
    chains = []
    for c in range(n):
        r = 0x10 + c * 32
        count, flag, _, off = struct.unpack_from("<BBHI", b, r)
        head = dict(count=count, flag=flag, scale=struct.unpack_from("<3f", b, r + 16), rest=b[r + 4:r + 16].hex(), tail=b[r + 28:r + 32].hex())
        nodes = []
        for k in range(count):
            o = r + off + k * 96
            t, j, jf = struct.unpack_from("<IHH", b, o)
            f = lambda a, n=1: struct.unpack_from(f"<{n}f", b, o + a)
            nodes.append(dict(type=t, joint=j, jflag=jf, zero8=b[o + 8:o + 16].hex(), min=f(0x10, 3), f1c=f(0x1C)[0], max=f(0x20, 3),
                              f2c=f(0x2C)[0], f30=f(0x30)[0], b34=b[o + 0x34:o + 0x38].hex(), f38=f(0x38)[0], f3c=f(0x3C)[0],
                              link=struct.unpack_from("<H", b, o + 0x40)[0], mid=b[o + 0x42:o + 0x4C].hex(), f4c=f(0x4C)[0], end=b[o + 0x50:o + 0x60].hex()))
        chains.append(dict(head, nodes=nodes))
    return dict(ver=ver, unk=unk, size=size, chains=chains)


# bd2902's cape (Femmes Fatales, three strands off the chest): free swing (limit flag off)
CAPE = dict(min=(-0.054831139743328094,) * 3, f1c=5.0, max=(0.054831139743328094,) * 3, f2c=0.2, f30=1.0,
            b34=bytes((0, 1, 0, 0)), f38=5.0, f3c=0.1, f4c=0.8)


def build(chains, params=CAPE):
    """chains: [[joint id, ...] root first, ...] (ids < 256) -> rChain bytes. Every node gets params;
    a node links its neighbours in the chain (the root its child, the tip its parent)."""
    n_nodes = sum(len(c) for c in chains)
    data = bytearray(16 + 32 * len(chains) + 96 * n_nodes)
    struct.pack_into("<4sHHII", data, 0, b"CHN\0", 0x0618, 8, len(data) - 16, len(chains))
    node_at = 16 + 32 * len(chains)
    for ci, chain in enumerate(chains):
        if not 2 <= len(chain) <= 255 or max(chain) > 255:
            raise ValueError(f"chain {chain}: 2-255 joints, ids below 256")
        r = 16 + ci * 32
        struct.pack_into("<BBHI", data, r, len(chain), 1, 0, node_at - r)
        struct.pack_into("<3f", data, r + 16, 1.0, 1.0, 1.0)
        for k, j in enumerate(chain):
            o = node_at + k * 96
            links = [x for x in (chain[k - 1] if k else None, chain[k + 1] if k + 1 < len(chain) else None) if x is not None]
            if k == 0:
                links = links[::-1]
            struct.pack_into("<IHH", data, o, 3 if k == 0 else 2, j, len(links))
            struct.pack_into("<3ff3ff", data, o + 0x10, *params["min"], params["f1c"], *params["max"], params["f2c"])
            struct.pack_into("<f", data, o + 0x30, params["f30"])
            data[o + 0x34:o + 0x38] = params["b34"]
            struct.pack_into("<ff", data, o + 0x38, params["f38"], params["f3c"])
            data[o + 0x40:o + 0x40 + len(links)] = bytes(links)
            struct.pack_into("<f", data, o + 0x4C, params["f4c"])
        node_at += 96 * len(chain)
    return bytes(data)



# rChainCol ('CCL\0' v0x0618): what a part's chains collide with. 0x08 u32 count, 0x0C u32 size (file - 16),
# then 64 B capsules: u32 1, u16 joint a, i16 joint b (-1: a sphere/ellipsoid on a, the end vec3 is its scale ?),
# u32 1, f32 0, +0x10 vec3 offset on a, f32 0, +0x20 vec3 offset on b, +0x2C f32 radius, 16 B 0.
# Stock: bd2500 thighs 2->3 (0,20,0)-(0,0,0) r12 and 5->6; bd2700 chest 9->8 (0,45,0)-(0,15,0) r21.
def build_col(capsules):
    """capsules: [(joint a, joint b, (offset on a), (offset on b), radius), ...] -> rChainCol bytes."""
    data = bytearray(16 + 64 * len(capsules))
    struct.pack_into("<4sHHII", data, 0, b"CCL\0", 0x0618, 8, len(capsules), len(data) - 16)
    for k, (ja, jb, pa, pb, r) in enumerate(capsules):
        o = 16 + 64 * k
        struct.pack_into("<IHhI", data, o, 1, ja, jb, 1)
        struct.pack_into("<3f", data, o + 0x10, *pa)
        struct.pack_into("<3ff", data, o + 0x20, *pb, r)
    return bytes(data)


THIGHS_COL = [(2, 3, (0, 0, 0), (0, 0, 0), 13.0), (5, 6, (0, 0, 0), (0, 0, 0), 13.0)]
TORSO_COL = [(9, 8, (0, 45, 0), (0, 15, 0), 25.0)]  # bd2700's, 4 cm fatter

if __name__ == "__main__":
    import math
    for path in sys.argv[1:]:
        b = open(path, "rb").read()
        c = parse(b)
        print(f"== {path.split('/')[-1]} ver {c['ver']:#x} unk {c['unk']} size {c['size']} (file {len(b)}) chains {len(c['chains'])}")
        for ch in c["chains"]:
            print(f"  chain n{ch['count']} flag {ch['flag']} scale {ch['scale']} {ch['rest']} {ch['tail']}")
            for nd in ch["nodes"]:
                deg = lambda v: "/".join(f"{math.degrees(x):.0f}" for x in v)
                odd = [k for k in ("zero8", "mid", "end") if set(nd[k]) - {"0"}]
                print(f"    t{nd['type']} j{nd['joint']} jf{nd['jflag']} lim {deg(nd['min'])}..{deg(nd['max'])} f1c {nd['f1c']:.3g} f2c {nd['f2c']:.3g} "
                      f"f30 {nd['f30']:.3g} b34 {nd['b34']} f38 {nd['f38']:.3g} f3c {nd['f3c']:.3g} link j{nd['link']} f4c {nd['f4c']:.3g}" + (f" ODD {odd}" if odd else ""))
