# Blender headless: import an OBJ and render a textured preview PNG.
#   flatpak run org.blender.Blender -b --python blender_preview.py -- IN.obj OUT.png [azimuth_deg]
import bpy, math, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
az = math.radians(float(argv[2])) if len(argv) > 2 else math.radians(35)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=src, forward_axis="NEGATIVE_Z", up_axis="Y")
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
# LP2 stores masks in texture alpha; the OBJ importer wires that to opacity
for mat in bpy.data.materials:
    if mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                for l in list(n.inputs["Alpha"].links):
                    mat.node_tree.links.remove(l)
                n.inputs["Alpha"].default_value = 1.0
    mat.surface_render_method = "DITHERED"
# ...and Blender would premultiply colour by that mask on load (LP1 faces: alpha ~0 -> black skin)
for img in bpy.data.images:
    img.alpha_mode = "CHANNEL_PACKED"
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector((min(p[i] for p in pts) for i in range(3)))
hi = Vector((max(p[i] for p in pts) for i in range(3)))
c, r = (lo + hi) / 2, (hi - lo).length / 2

scn = bpy.context.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam)
cam.location = c + Vector((math.sin(az), -math.cos(az), 0.55)).normalized() * r * 2.6
cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.clip_end = r * 10
scn.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, az + 0.6)
scn.collection.objects.link(sun)
scn.world = bpy.data.worlds.new("w")
scn.world.color = (0.25, 0.25, 0.28)
scn.render.engine = "BLENDER_EEVEE"
scn.render.resolution_x = scn.render.resolution_y = 768
scn.render.filepath = dst
bpy.ops.render.render(write_still=True)
