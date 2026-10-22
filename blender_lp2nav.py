# Add an LP2 AI navmesh (and optionally its waypoints) to a .blend, to look at or check against the map.
#   flatpak run org.blender.Blender -b [MAP.blend] --python blender_lp2nav.py -- OUT.blend FILE.rAINavigationMeshList [FILE.rAIWayPoint]
# Collection "LP2 Navmesh": one mesh per area (own colour, face attribute lp2_flags), "links" (an edge
# between the centres of each pair of linked polygons) and "waypoints" (vertices). Map space as
# blender_layout.py: LP2 Y-up cm -> Blender Z-up m.
import bpy, colorsys, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2nav  # noqa: E402

SCALE = 0.01


def to_blender(p):
    return (p[0] * SCALE, -p[2] * SCALE, p[1] * SCALE)


def material(name, colour):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = (*colour, 1)
    return m


def add_object(col, name, verts, edges=(), faces=(), colour=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, list(edges), list(faces))
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    if colour:
        ob.color = (*colour, 1)
        me.materials.append(material("lp2_nav_" + name, colour))
    return ob


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    out, lnv = args[0], args[1]
    meshes = lp2nav.read_lnv(open(lnv, "rb").read())
    col = bpy.data.collections.new("LP2 Navmesh")
    bpy.context.scene.collection.children.link(col)
    for m in meshes:
        verts = [to_blender(v) for v in m["verts"]]
        leaves = [a for a in m["areas"] if not a["children"]] or [{"id": 0, "first": 0, "end": len(m["polys"])}]
        for k, a in enumerate(leaves):
            polys = m["polys"][a["first"]:a["end"]]
            used = sorted({i for p in polys for i in p["tri"]})
            remap = {v: i for i, v in enumerate(used)}
            colour = colorsys.hsv_to_rgb(k / max(1, len(leaves)), 0.6, 0.9)
            ob = add_object(col, "area_%d" % a["id"], [verts[i] for i in used],
                            faces=[[remap[i] for i in p["tri"]] for p in polys], colour=colour)
            attr = ob.data.attributes.new("lp2_flags", "INT", "FACE")
            for i, p in enumerate(polys):
                attr.data[i].value = p["flags"][0] if p["flags"] else 0
            ob["lp2_area"] = a["id"]
        centres = [tuple(sum(verts[i][c] for i in p["tri"]) / len(p["tri"]) + (0.05 if c == 2 else 0) for c in range(3))
                   for p in m["polys"]]
        edges = [(i, l[0]) for i, p in enumerate(m["polys"]) for l in p["links"] if l[0] > i]
        add_object(col, "links", centres, edges=edges, colour=(1, 1, 1))
    if len(args) > 2:
        way = lp2nav.read_way(open(args[2], "rb").read())
        ob = add_object(col, "waypoints", [to_blender(p["pos"]) for p in way["points"]], colour=(1, 0.8, 0))
        attr = ob.data.attributes.new("lp2_cover", "INT", "POINT")
        for i, p in enumerate(way["points"]):
            v = p["a"][0] if p["a"] else 0
            attr.data[i].value = v - (1 << 32) if v >= 1 << 31 else v  # stored signed
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
    print("lp2nav: saved", out)


main()
