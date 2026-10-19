# Blender headless: add LP1 multiplayer layout points (lp1points.py JSON) to a map .blend as empties.
#   flatpak run org.blender.Blender -b MAP.blend --python blender_lp1points.py -- POINTS.json [SCALE]
# Collection "LP1 layout" > one collection per distinct layout ("m0v0 00/10/30/40") > spawns / teams / vs /
# weapons / objects / other. Only the first layout is visible. Every empty keeps the source data as custom
# properties (lp1_pos_cm, lp1_yaw, lp1_kind, lp1_role, lp1_model, lp2_kind) so a porting tool can read them
# straight back; the empty's transform is only for viewing (cm -> SCALE, Y-up -> Z-up, yaw about Z).
import bpy, json, math, sys
argv = sys.argv[sys.argv.index("--") + 1:]
data = json.load(open(argv[0]))
scale = float(argv[1]) if len(argv) > 1 else 0.01

# LP2 rInitPosSet: Kind 0 = FFA starts, Kind 1 / Kind 2 = the two teams
LP2_KIND = {"start": 0, "team_a": 1, "team_b": 2}
GROUP = {"start": "spawns", "team_a": "teams", "team_b": "teams", "team_c": "teams", "team_d": "teams",
         "vs": "vs", "weapon": "weapons", "object": "objects"}
LOOK = {"spawns": ("SINGLE_ARROW", 1.5), "teams": ("CONE", 0.6), "vs": ("CUBE", 1.5), "weapons": ("SPHERE", 0.4),
        "objects": ("CIRCLE", 2.0), "other": ("PLAIN_AXES", 1.0)}

old = bpy.data.collections.get("LP1 layout")
if old:  # re-runnable: replace the previous import
    for c in list(old.children_recursive) + [old]:
        for ob in list(c.objects):
            bpy.data.objects.remove(ob)
        bpy.data.collections.remove(c)
root = bpy.data.collections.new("LP1 layout")
bpy.context.scene.collection.children.link(root)

for si, s in enumerate(data["sets"]):
    first = s["ids"][0]
    coll = bpy.data.collections.new(f"m{first[0]}v{first[1]} {'/'.join(s['ids'])}")
    root.children.link(coll)
    subs = {}
    counts = {}
    for rec in [dict(r, src="point") for r in s["points"]] + [dict(r, src="object") for r in s["objects"]]:
        g = GROUP.get(rec["role"], "other")
        if g not in subs:
            subs[g] = bpy.data.collections.new(f"{g} ({coll.name.split()[0]})")
            coll.children.link(subs[g])
        label = rec.get("model") or rec["role"]
        counts[label] = counts.get(label, 0) + 1
        ob = bpy.data.objects.new(f"{label}_{counts[label]:02d}", None)
        ob.empty_display_type, ob.empty_display_size = LOOK[g]
        x, y, z = rec["pos"]
        ob.location = (x * scale, -z * scale, y * scale)
        ob.rotation_euler = (0.0, 0.0, math.radians(rec["yaw"]))
        ob["lp1_pos_cm"] = list(rec["pos"])
        ob["lp1_yaw"] = rec["yaw"]
        ob["lp1_kind"] = rec["kind"]
        ob["lp1_role"] = rec["role"]
        ob["lp1_src"] = rec["src"]
        if rec.get("model"):
            ob["lp1_model"] = rec["model"]
        if rec["role"] in LP2_KIND:
            ob["lp2_kind"] = LP2_KIND[rec["role"]]
        subs[g].objects.link(ob)
    if si:
        coll.hide_viewport = True
        coll.hide_render = True
    print(f"{coll.name}: " + ", ".join(f"{k} {len(v.objects)}" for k, v in subs.items()))

bpy.ops.wm.save_mainfile(compress=True)
print("saved", bpy.data.filepath)
