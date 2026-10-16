# Add a map's spawn points and object placements to its .blend as marker objects.
#   flatpak run org.blender.Blender -b MAP.blend --python blender_layout.py -- OUT.blend FILE.rInitPosSet|FILE.rObjSet ...
# Markers: cones for spawns (pointing along Dir, team-coloured), cubes for weapons, cylinders for
# vehicles, spheres for posts. Each carries lp2_* custom properties with the original record.
import bpy, math, os, sys
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import objset, xfs  # noqa: E402

SCALE = 0.01
COLOURS = {"team1": (0.1, 0.4, 1.0), "team2": (1.0, 0.15, 0.1), "spawn": (0.9, 0.9, 0.9),
           "weapon": (1.0, 0.85, 0.0), "vehicle": (0.1, 1.0, 0.3), "post": (0.9, 0.2, 1.0), "group2": (0.5, 0.5, 0.5)}


def to_blender(p):  # LP2 Y-up cm -> Blender Z-up m
    return Vector((p[0], -p[2], p[1])) * SCALE


def material(name):
    m = bpy.data.materials.get("lp2_marker_" + name)
    if m is None:
        m = bpy.data.materials.new("lp2_marker_" + name)
        m.use_nodes = True
        nt = m.node_tree
        for n in list(nt.nodes):
            if n.type == "BSDF_PRINCIPLED":
                nt.nodes.remove(n)
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*COLOURS[name], 1)
        em.inputs["Strength"].default_value = 3
        nt.links.new(em.outputs[0], next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL").inputs[0])
    return m


def marker(col, shape, colour, loc, yaw_deg, props, size=1.5):
    meshes = {"cone": lambda: bpy.ops.mesh.primitive_cone_add(radius1=size * 0.6, depth=size * 1.6),
              "cube": lambda: bpy.ops.mesh.primitive_cube_add(size=size),
              "cyl": lambda: bpy.ops.mesh.primitive_cylinder_add(radius=size, depth=size * 0.5),
              "sphere": lambda: bpy.ops.mesh.primitive_uv_sphere_add(radius=size * 0.7)}
    meshes[shape]()
    ob = bpy.context.active_object
    for c in ob.users_collection:
        c.objects.unlink(ob)
    col.objects.link(ob)
    ob.location = loc + Vector((0, 0, size))
    if shape == "cone":  # lie the cone down and aim it along the spawn direction
        ob.rotation_euler = (math.radians(90), 0, math.radians(yaw_deg + 180))
    else:
        ob.rotation_euler = (0, 0, math.radians(yaw_deg))
    ob.data.materials.append(material(colour))
    for k, v in props.items():
        ob["lp2_" + k] = v if not isinstance(v, list) else str(v)
    return ob


def add_file(path):
    name = os.path.basename(path)
    col = bpy.data.collections.new("layout " + name)
    bpy.context.scene.collection.children.link(col)
    b = open(path, "rb").read()
    if b[:4] == b"XFS\0":
        for i, sp in enumerate(xfs.parse(b)["mInitPosSet"]["mpArray"]):
            team = {1: "team1", 2: "team2"}.get(sp["Kind"], "spawn")
            marker(col, "cone", team, to_blender(sp["Pos"]), sp["Dir"],
                   dict(index=i, kind=sp["Kind"], dir=sp["Dir"], weapon_r=sp["WeaponR"], weapon_l=sp["WeaponL"]))
    else:
        _, recs, _ = objset.parse(b)
        for i, r in enumerate(recs):
            shape = {"weapon": "cube", "vehicle": "cyl"}.get(r["group"], "sphere")
            marker(col, shape, r["group"], to_blender(r["pos"]), r["rot"][1],
                   dict(index=i, group=r["group"], item=f"{r['item']:#x}", phase=r["phase"], rot=r["rot"]))
    print("LP2 layout", name, len(col.objects))


argv = sys.argv[sys.argv.index("--") + 1:]
for p in argv[1:]:
    add_file(p)
bpy.ops.wm.save_as_mainfile(filepath=argv[0])
print("LP2 saved", argv[0])
