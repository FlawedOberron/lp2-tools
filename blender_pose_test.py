# Render a character .blend in bind pose and in a test pose (arms down, head turned).
#   flatpak run org.blender.Blender -b FILE.blend --python blender_pose_test.py -- OUT_PREFIX
import bpy, math, sys
from mathutils import Vector, Euler
out = sys.argv[sys.argv.index("--") + 1]
scn = bpy.context.scene
for mat in bpy.data.materials:
    mat.surface_render_method = "DITHERED"
arm = bpy.data.objects["LP2_rig"]
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scn.collection.objects.link(cam); scn.camera = cam
cam.location = (1.6, -3.6, 1.0); cam.rotation_euler = (Vector((0, 0, 0.15)) - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 50
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sun.data.energy = 4
sun.rotation_euler = (0.9, 0.2, 0.5); scn.collection.objects.link(sun)
scn.world = bpy.data.worlds.new("w"); scn.world.color = (0.35, 0.35, 0.4)
scn.render.engine = "BLENDER_EEVEE"; scn.render.resolution_x = 700; scn.render.resolution_y = 900
scn.render.filepath = out + "_bind.png"; bpy.ops.render.render(write_still=True)
pb = arm.pose.bones
from mathutils import Matrix
def rot(name, axis, deg):
    """Rotate a pose bone about a world (armature-space) axis through its head."""
    if name not in pb:
        return
    bpy.context.view_layer.update()
    m = pb[name].matrix.copy()
    piv = m.translation.copy()
    pb[name].matrix = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-piv) @ m
rot("l_upperarm", "Y", -70); rot("r_upperarm", "Y", 70)    # upper arms down to the sides
rot("l_forearm", "X", 70); rot("r_forearm", "X", 70)     # elbows bend forward
rot("head", "Z", 40)                          # head turns
rot("l_thigh", "X", 30); rot("r_shin", "X", -30)    # one leg forward, one back (if those are thighs)
bpy.context.view_layer.update()
scn.render.filepath = out + "_posed.png"; bpy.ops.render.render(write_still=True)
print("BONES", [b.name for b in arm.data.bones])
