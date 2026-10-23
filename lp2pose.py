#!/usr/bin/env python3
"""A motion's first frame applied to an rModel's skinned vertices (the editor's VS models in their in-game pose).

  lp2pose.py MOTIONS.rMotionList                list motions: index, frames, root height, tracks
  lp2pose.py MOTIONS.rMotionList MODEL.rModel N report model height range bind vs posed (motion N)

rMotionList (LMT v0x38): 'LMT\\0', u16 version, u16 motion count, u32 offsets (0 = none).
Motion: u32 track offset, u32 track count, u32 frames, i32 loop frame, ...
Position tracks far from the bone offset are IK targets and are skipped (see pose_worlds).
Track (0x24 bytes): u8 buffer type, u8 usage (0 local rotation, 1 local position, 2 scale, 3 / 4 root rotation /
  position), u8 joint type, u8 joint id (0xff = the model root), f32 weight, u32 buffer size, u32 buffer offset,
  f32 ref[4] (= the first key: quaternion xyzw or position), u32 extremes offset.
The first frame comes from ref alone (checked against decoded 14-bit keys / 4096), so no key decoding is needed.
"""
import struct, sys

import numpy as np

import mod2obj


def motions(b):
    """-> [None | dict(frames, tracks=[(usage, joint, ref)])] by motion index."""
    if b[:4] != b"LMT\0":
        raise ValueError("not an LMT file")
    n = struct.unpack_from("<H", b, 6)[0]
    out = []
    for o in struct.unpack_from(f"<{n}I", b, 8):
        if not o:
            out.append(None)
            continue
        to, nt, nf = struct.unpack_from("<III", b, o)
        tr = []
        for t in range(nt):
            e = to + t * 0x24
            _bt, usage, _jt, joint = b[e:e + 4]
            tr.append((usage, joint, struct.unpack_from("<4f", b, e + 16)))
        out.append(dict(frames=nf, tracks=tr))
    return out


# buffer type -> key size; every key ends with its length in frames (the keys of a track add up to frames - 1)
KEY_SIZE = {1: 12, 2: 12, 3: 16, 4: 8, 5: 4, 6: 8, 7: 4}


def decode_key(b, bt, o, ext):
    """-> (value[4], frames until the next key). ext: (range[4], min[4]) for the 'bilinear' types 4 / 5 / 7."""
    if bt in (1, 2):
        v = struct.unpack_from("<3f", b, o)
        return ((*v, 1.0) if bt == 1 else (*v, max(0.0, 1 - sum(c * c for c in v)) ** 0.5)), 1
    if bt == 3:
        *v, f = struct.unpack_from("<3fI", b, o)
        return (*v, 1.0), f
    if bt == 4:
        q = struct.unpack_from("<4H", b, o)
        return tuple(ext[1][i] + q[i] / 65535 * ext[0][i] for i in range(3)) + (1.0,), q[3]
    if bt == 5:
        q = b[o:o + 4]
        return tuple(ext[1][i] + q[i] / 255 * ext[0][i] for i in range(3)) + (1.0,), q[3]
    if bt == 6:
        x = struct.unpack_from("<Q", b, o)[0]
        c = [(x >> s) & 0x3FFF for s in (42, 28, 14, 0)]
        return tuple((k - 0x4000 if k > 0x1FFF else k) / 4096 for k in c), x >> 56
    if bt == 7:
        x = struct.unpack_from("<I", b, o)[0]
        c = [(x >> s) & 0x7F for s in (21, 14, 7, 0)]
        return tuple(ext[1][i] + c[i] / 127 * ext[0][i] for i in range(4)), x >> 28
    raise ValueError(f"buffer type {bt}")


def tracks_keys(b, o):
    """motion at offset o -> (frames, [(usage, joint, [(frame, value[4])])]): every key decoded."""
    to, nt, nf = struct.unpack_from("<III", b, o)
    out = []
    for t in range(nt):
        e = to + t * 0x24
        bt, usage, _jt, joint = b[e:e + 4]
        size, off = struct.unpack_from("<II", b, e + 8)
        ref = struct.unpack_from("<4f", b, e + 16)
        exo = struct.unpack_from("<I", b, e + 32)[0]
        if not size or bt not in KEY_SIZE:
            out.append((usage, joint, [(0, ref)]))
            continue
        ext = (struct.unpack_from("<4f", b, exo), struct.unpack_from("<4f", b, exo + 16)) if exo else None
        keys, f = [], 0
        for k in range(size // KEY_SIZE[bt]):
            v, d = decode_key(b, bt, off + k * KEY_SIZE[bt], ext)
            keys.append((f, v))
            f += d
        out.append((usage, joint, keys))
    return nf, out


def sample(keys, f, quat):
    """value at frame f: linear between keys (normalised for quaternions), held after the last."""
    if f <= keys[0][0]:
        return keys[0][1]
    for (f0, a), (f1, b) in zip(keys, keys[1:]):
        if f <= f1:
            t = (f - f0) / max(1, f1 - f0)
            if quat and sum(x * y for x, y in zip(a, b)) < 0:
                b = tuple(-x for x in b)
            v = tuple(x + (y - x) * t for x, y in zip(a, b))
            if quat:
                n = sum(x * x for x in v) ** 0.5 or 1.0
                v = tuple(x / n for x in v)
            return v
    return keys[-1][1]


def ik_target(joint, pos, bind_pos):
    """position tracks far from the bone's own offset are IK targets (the game solves the chain at runtime)."""
    d = sum((a - b) ** 2 for a, b in zip(pos, bind_pos)) ** 0.5
    return joint != 0 and d > max(20.0, 0.5 * sum(b * b for b in bind_pos) ** 0.5)


def quat_mat(q):
    """xyzw -> 3x3 for row vectors (v' = v @ R)."""
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-8:
        return np.eye(3)
    x, y, z, w = (c / n ** 0.5 for c in q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])


def bind_worlds(bones):
    """model-space bind matrices (4x4, row vectors) from the local chain."""
    loc = [np.array(bn["local"]).reshape(4, 4) for bn in bones]
    world = [None] * len(bones)
    for i, bn in enumerate(bones):
        p = bn["parent"]
        world[i] = loc[i] @ world[p] if p < len(bones) and p != i and world[p] is not None else loc[i]
    return loc, world


def pose_worlds(bones, motion):
    """the motion's first frame: tracked joints get its rotation / position, the rest keep the bind local."""
    loc, _ = bind_worlds(bones)
    by_joint = {bn["joint"]: i for i, bn in enumerate(bones)}
    loc = [m.copy() for m in loc]
    root = np.eye(4)
    for usage, joint, ref in motion["tracks"]:
        if joint == 0xFF:
            if usage == 3:
                root[:3, :3] = quat_mat(ref)
            elif usage == 4:
                root[3, :3] = ref[:3]
            continue
        i = by_joint.get(joint)
        if i is None:
            continue
        if usage == 0:
            loc[i][:3, :3] = quat_mat(ref)
        elif usage == 1:
            # leg / arm IK targets come as position tracks far from the bone's own offset (the game solves the
            # chain at runtime): only joint 0 (hips height) and offsets near the bind one move a bone
            bind = loc[i][3, :3]
            if joint == 0 or np.linalg.norm(np.array(ref[:3]) - bind) <= max(20.0, 0.5 * np.linalg.norm(bind)):
                loc[i][3, :3] = ref[:3]
    world = [None] * len(bones)
    for i, bn in enumerate(bones):
        p = bn["parent"]
        world[i] = loc[i] @ (world[p] if p < len(bones) and p != i and world[p] is not None else root)
    return world


def skin_matrices(bones, motion):
    """per bone: bind-model-space -> posed model space (row vectors)."""
    _, bind = bind_worlds(bones)
    pose = pose_worlds(bones, motion)
    return [np.linalg.inv(bind[i]) @ pose[i] for i in range(len(bones))]


def pose_point(p, skin, mats):
    v = np.array([p[0], p[1], p[2], 1.0])
    out = np.zeros(4)
    for i, w in skin:
        out += w * (v @ mats[i if i < len(mats) else 0])
    return tuple(out[:3])


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ms = motions(open(sys.argv[1], "rb").read())
    if len(sys.argv) == 2:
        for k, m in enumerate(ms):
            if m:
                lift = [r[1] for u, j, r in m["tracks"] if u == 1 and j == 0]
                print(f"{k:3d} {m['frames']:4d} frames  joint 0 y {lift[0] if lift else '-'}  {len(m['tracks'])} tracks")
        return
    b = open(sys.argv[2], "rb").read()
    bones, _ = mod2obj.read_bones(b)
    mats = skin_matrices(bones, ms[int(sys.argv[3])])
    M = mod2obj.read_model(b)
    ys, py = [], []
    for m in M["meshes"]:
        if m["lodmask"] & 1 == 0 or m["fmt"] not in mod2obj.SKIN:
            continue
        g = mod2obj.mesh_geometry(b, m, M)
        if not g:
            continue
        base = M["vb"] + m["voff"]
        for i, p in g[0].items():
            o = base + (m["vbase"] + i) * m["stride"]
            sk = mod2obj.vertex_skin(b[o:o + m["stride"]], mod2obj.SKIN[m["fmt"]])
            ys.append(p[1])
            py.append(pose_point(p, sk, mats)[1])
    print(f"bind y {min(ys):.1f} .. {max(ys):.1f}   posed y {min(py):.1f} .. {max(py):.1f}  ({len(ys)} vertices)")


if __name__ == "__main__":
    main()
