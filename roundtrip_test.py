# Arrange a fresh import of hd/bd/lg/bk2900 into the exporter's LPC_ layout and export it.
import bpy, sys
argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]
root = bpy.data.collections.new("LPC_rt29_FF_Roundtrip")
bpy.context.scene.collection.children.link(root)
for pfx, part in (("hd", "head"), ("bd", "body"), ("lg", "legs"), ("bk", "back")):
    src = bpy.data.collections.get(f"{pfx}2900 Hi")
    c = bpy.data.collections.new(part)
    root.children.link(c)
    for o in src.objects:
        c.objects.link(o)
sys.argv = ["blender", "--", out]
P = "/home/flawedoberron/Projects/lp2-tools/lp2_blender_export.py"
exec(compile(open(P).read(), P, "exec"), {"__name__": "__main__", "__file__": P})
