# Top-down render of a .blend: flatpak run org.blender.Blender -b FILE.blend --python blender_top.py -- OUT.png [collection-substring] [hide,name,parts]
import bpy, sys
from mathutils import Vector
argv = sys.argv[sys.argv.index("--") + 1:]
only = argv[1] if len(argv) > 1 else None
scn = bpy.context.scene
for o in scn.objects:
    if only and not any(only in c.name for c in o.users_collection):
        o.hide_render = True
for o in scn.objects:  # backdrop meshes (sky dome / far ring), named via --hide
    if any(h in o.name for h in (argv[2].split(",") if len(argv) > 2 else [])):
        o.hide_render = True
objs = [o for o in scn.objects if o.type == "MESH" and not o.hide_render]
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scn.collection.objects.link(cam)
cam.data.type = "ORTHO"; cam.data.ortho_scale = max(hi.x - lo.x, hi.y - lo.y)
cam.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z + 10); cam.data.clip_end = (hi.z - lo.z) + 100
scn.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sun.data.energy = 3; scn.collection.objects.link(sun)
scn.world = bpy.data.worlds.new("w"); scn.world.color = (0.2, 0.2, 0.22)
scn.render.engine = "BLENDER_EEVEE"; scn.render.resolution_x = scn.render.resolution_y = 900
scn.render.filepath = argv[0]
bpy.ops.render.render(write_still=True)
for c in bpy.data.collections: print("COL", c.name, len(c.objects))
