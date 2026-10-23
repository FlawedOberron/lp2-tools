# The LP2 character skeleton as a Blender file, and renaming older rigs' bones to readable names.
#
#   flatpak run org.blender.Blender -b --python lp2_skeleton.py -- make OUT.blend
#       an armature "LP2_rig" with every standard joint (lp2bones.py names, ids kept as lp2_joint), from the
#       Femmes Fatales (hm29) part templates' bind pose: rig new parts on it, or import parts onto it.
#   flatpak run org.blender.Blender -b FILE.blend --python lp2_skeleton.py -- rename
#       every armature's jNNN bones -> names (Blender renames the meshes' vertex groups along), saved in place
#       (Blender keeps the previous save as FILE.blend1).
import bpy, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2_blender_import as I  # noqa: E402
import lp2bones as B  # noqa: E402
import mod2obj as M  # noqa: E402

RAW = os.path.expanduser("~/Projects/lp2-assets/raw/CustomParts")
TEMPLATES = [RAW + f"/{p}2900/model/hm/hm29/{p}2900/{p}2900.rModel" for p in ("bd", "lg", "bk", "hd")]


def make(out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm = I.get_armature("LP2_rig")
    sources = [(p, M.read_bones(open(p, "rb").read())[0]) for p in TEMPLATES]
    I._READABLE = True
    I.build_armature(arm, I.merge_skeletons(sources))
    arm.data.display_type = "STICK"
    arm["lp2_skeleton"] = "LP2 character joints (lp2bones.py names); -X = the character's left, facing +Z in game"
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
    print(f"wrote {out}: {len(arm.data.bones)} bones: " + ", ".join(b.name for b in arm.data.bones))


def rename():
    total = 0
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE":
            n = I.rename_old_bones(ob)
            custom = [b.name for b in ob.data.bones if B.joint_of(b.name) is None]
            print(f"{ob.name}: {n} bone(s) renamed; custom bones kept: {', '.join(custom) or '-'}")
            total += n
    if total:
        bpy.ops.wm.save_mainfile()
    print(f"{bpy.data.filepath}: {total} renamed")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if args[:1] == ["make"] and len(args) == 2:
        make(args[1])
    elif args[:1] == ["rename"]:
        rename()
    else:
        raise SystemExit("usage: -- make OUT.blend | (with a .blend open) -- rename")
