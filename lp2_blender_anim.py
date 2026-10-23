# Lost Planet 2 soldier + weapon + motion banks -> Blender (one action per motion, on the LP2_rig armature).
#
#   flatpak run org.blender.Blender -b --python lp2_blender_anim.py -- OUT.blend --parts A.rModel [B.rModel ...]
#       --weapon WP.rModel [--hand 20] --motions BANK.lmt [BANK.lmt ...] [--only 0-40]
#
# Parts: lp2_blender_import (shared LP2_rig, bones "jNNN"). The weapon is its own object following joint --hand
# (j020 = right hand; +X is the soldier's left: j101 on that forearm is the shield mount) through a Child Of
# constraint. Actions are named <bank>_<index> ("hmf8_1000_042"), kept with a fake user, sampled every frame from
# lp2pose.tracks_keys (keys linear between). Position tracks that are IK targets are skipped, as in lp2pose: arms and
# legs can differ a little from the game, which bends them with IK at runtime.
import bpy, os, struct, sys
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2_blender_import as I  # noqa: E402
import lp2pose  # noqa: E402
import lp2bones as B  # noqa: E402
import mod2obj as M  # noqa: E402


def lp2_local(q, t):
    """rotation quaternion xyzw + translation (cm) -> column-convention Matrix (cm)."""
    m = Quaternion((q[3], q[0], q[1], q[2])).to_matrix().to_4x4()
    m.translation = Vector(t[:3])
    return m


def to_blender(m):
    out = I.AXIS @ m
    out.translation = out.translation * I.SCALE
    return out


def skeleton(paths):
    """joint -> (parent joint | None, bind local Matrix (cm)), merged like the importer (first part to define wins)."""
    joints = {}
    for p in sorted(paths, key=I.part_rank):
        bones, _ = M.read_bones(open(p, "rb").read())
        for bn in bones:
            parent = None if bn["parent"] == 255 else bones[bn["parent"]]["joint"]
            joints.setdefault(bn["joint"], (parent, I.mat_from_lp2(bn["local"])))
    return joints


def order(joints):
    done, out = set(), []
    while len(out) < len(joints):
        for j, (p, _) in joints.items():
            if j not in done and (p is None or p in done or p not in joints):
                done.add(j)
                out.append(j)
    return out


def bind_frames(joints, seq):
    world = {}
    for j in seq:
        p, loc = joints[j]
        world[j] = (world[p] @ loc) if p in world else loc
    return {j: to_blender(m) for j, m in world.items()}


def make_action(arm, name, nf, tracks, joints, seq, bind_bl):
    by = {}
    root_rot, root_pos = (0, 0, 0, 1), (0, 0, 0)
    for usage, joint, keys in tracks:
        by.setdefault(joint, {})[usage] = keys
    pb = arm.pose.bones
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data.action = act  # Blender 4.4+ layered actions: curves live in the slot made for arm
    curves = {}
    for j in seq:
        bname = B.name_of(j) if B.name_of(j) in pb else f"j{j:03d}"  # a rig from before readable names
        if bname not in pb:
            continue
        dp = f'pose.bones["{bname}"]'
        curves[j] = ([act.fcurve_ensure_for_datablock(arm, dp + ".location", index=i, group_name=bname) for i in range(3)],
                     [act.fcurve_ensure_for_datablock(arm, dp + ".rotation_quaternion", index=i, group_name=bname)
                      for i in range(4)])
    data = {j: ([[] for _ in range(3)], [[] for _ in range(4)]) for j in curves}
    bones = arm.data.bones
    for f in range(max(1, nf)):
        r = by.get(0xFF, {})
        rr = lp2pose.sample(r[3], f, True) if 3 in r else root_rot
        rp = lp2pose.sample(r[4], f, False) if 4 in r else root_pos
        world = {}
        root = lp2_local(rr, rp)
        for j in seq:
            p, bind = joints[j]
            t = by.get(j, {})
            q = lp2pose.sample(t[0], f, True) if 0 in t else None
            pos = lp2pose.sample(t[1], f, False) if 1 in t else None
            loc = bind.copy()
            if q is not None:
                trans = loc.translation.copy()
                loc = Quaternion((q[3], q[0], q[1], q[2])).to_matrix().to_4x4()
                loc.translation = trans
            if pos is not None and not lp2pose.ik_target(j, pos[:3], tuple(bind.translation)):
                loc.translation = Vector(pos[:3])
            world[j] = (world[p] if p in world else root) @ loc
        pose_arm = {}
        for j in seq:
            if j not in curves:
                continue
            b = bones[B.name_of(j) if B.name_of(j) in bones else f"j{j:03d}"]
            pose_arm[j] = to_blender(world[j]) @ bind_bl[j].inverted() @ b.matrix_local
            if b.parent:
                pj = b.parent["lp2_joint"] if "lp2_joint" in b.parent else None
                parent_pose = pose_arm.get(pj, b.parent.matrix_local)
                basis = (b.parent.matrix_local.inverted() @ b.matrix_local).inverted() @ parent_pose.inverted() @ pose_arm[j]
            else:
                basis = b.matrix_local.inverted() @ pose_arm[j]
            lt, rq, _ = basis.decompose()
            for i in range(3):
                data[j][0][i] += (f, lt[i])
            for i in range(4):
                data[j][1][i] += (f, rq[i])
    for j, (locs, rots) in data.items():
        for fc, pts in zip(curves[j][0] + curves[j][1], locs + rots):
            fc.keyframe_points.add(len(pts) // 2)
            fc.keyframe_points.foreach_set("co", pts)
            fc.update()
    return act


def main(argv):
    out = argv[0]
    opt, key = {}, None
    for a in argv[1:]:
        if a.startswith("--"):
            key = a[2:]
            opt[key] = []
        else:
            opt[key].append(a)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = opt["parts"]
    arm = I.import_models(parts)
    for b in arm.pose.bones:
        b.rotation_mode = "QUATERNION"
    joints = skeleton(parts)
    seq = order(joints)
    bind_bl = bind_frames(joints, seq)
    if "weapon" in opt:
        hand = int((opt.get("hand") or ["20"])[0])
        wrig = I.get_armature("weapon_rig")
        before = set(bpy.data.objects)
        I.import_models(opt["weapon"], rig_name="weapon_rig")
        for ob in set(bpy.data.objects) - before:  # rigid weapon meshes come in unparented
            if ob.type == "MESH" and ob.parent is None:
                ob.parent = wrig
        con = wrig.constraints.new("CHILD_OF")
        hand_bone = B.name_of(hand) if B.name_of(hand) in arm.data.bones else f"j{hand:03d}"
        con.target, con.subtarget = arm, hand_bone
        # the weapon's origin sits on the joint's own frame, not the bone's aimed one: pose @ inverse = joint frame
        con.inverse_matrix = arm.data.bones[hand_bone].matrix_local.inverted() @ bind_bl[hand]
    lo, hi = 0, 10 ** 6
    if opt.get("only"):
        a, _, b = opt["only"][0].partition("-")
        lo, hi = int(a), int(b or a)
    arm.animation_data_create()
    count, first = 0, None
    for path in opt.get("motions", []):
        b = open(path, "rb").read()
        bank = os.path.splitext(os.path.basename(path))[0]
        n = struct.unpack_from("<H", b, 6)[0]
        for k, o in enumerate(struct.unpack_from(f"<{n}I", b, 8)):
            if not o or not lo <= k <= hi:
                continue
            nf, tracks = lp2pose.tracks_keys(b, o)
            act = make_action(arm, f"{bank}_{k:03d}", nf, tracks, joints, seq, bind_bl)
            act.frame_range = (0, max(1, nf - 1))
            first = first or act
            count += 1
    if first:
        arm.animation_data.action = first
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = 0, int(first.frame_range[1])
    bpy.context.scene.render.fps = 30
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"LP2 saved {out}: {count} actions")


if __name__ == "__main__" and "--" in sys.argv:
    main(sys.argv[sys.argv.index("--") + 1:])
