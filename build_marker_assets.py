#!/usr/bin/env python3
"""Game models for the Blender map markers (blender_lp2_map_markers.py): every VS type, the fixed weapons
and the data posts, as OBJ + DDS, then (blender_marker_assets.py) one lp2_marker_assets.blend.

  build_marker_assets.py GAME_DIR OUT_DIR [KEY...]   (KEYs: only those, added to OUT_DIR's manifest)

GAME_DIR: the Lost Planet 2 folder. Each type's archive is nativePC/arcLp2Xml/autoArc/u<Vs|Wp|Om><id>.arc;
its model = the largest rModel in the type's own folder (model/vs/vsXX/, model/wp/wpXX/, model/om/omXXXX/),
else the largest one under model/vs|wp|om/ (types that borrow another folder's model, e.g. 0x53 -> vs03), else under
model/ (Akrid VS: 0xd4's is model/ak/ak6b/vsd4, 0x1a's model/ak/ak00).
VS models are posed in their motion list's motion 0, first frame (lp2pose.py); types where that leaves them more
than 60 cm under the origin (flying, bosses, a few others) keep the bind pose; any VS still under the origin is lifted so its lowest point is on it.
Slot weapons (0 KB archives) have no model: the add-on keeps a plain shape for them.
Writes OUT_DIR/<key>/<model>.obj (+ .mtl, textures as .dds) and OUT_DIR/manifest.json {key: obj path};
keys: vs_66, wp_42, om_7100.
"""
import glob, json, os, re, subprocess, sys, tempfile, zlib
import arcx

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES = arcx.load_types()


def find_arc(auto, prefix, tag):
    for p in glob.glob(os.path.join(auto, f"u{prefix}*.arc")):
        if os.path.basename(p)[1 + len(prefix):-4].lower() == tag:
            return p
    return None


def pick_model(data, kind, tag):
    own, other, anywhere = [], [], []
    for name, th, cs, ds, _fl, _off in arcx.entries(data):
        if TYPES.get(th) != "rModel":
            continue
        low = name.lower()
        if low.startswith(f"model\\{kind}\\{kind}{tag}\\"):
            own.append((ds, name))
        elif low.startswith(f"model\\{kind}\\"):
            other.append((ds, name))
        elif low.startswith("model\\"):
            anywhere.append((ds, name))
    return max(own or other or anywhere or [(0, None)])[1]


def pick_motions(data, kind):
    """the archive's own rMotionList (motion/vs/vsXX/vsXX_mot): VS models are posed in its motion 0 (standing idle,
    the unmanned stance; the bind pose has the origin at the hips, so the model sat half under the floor)."""
    best = None
    for name, th, _cs, ds, _fl, _off in arcx.entries(data):
        if TYPES.get(th) == "rMotionList" and name.lower().startswith(f"motion\\{kind}\\"):
            best = max(best or (0, None), (ds, name))
    return best[1] if best else None


def lowest(obj):
    return min((float(l.split()[2]) for l in open(obj) if l.startswith("v ")), default=0.0)


def lift(obj, dy):
    out = []
    for l in open(obj):
        if l.startswith("v "):
            x, y, z = (float(v) for v in l.split()[1:4])
            l = "v %.5f %.5f %.5f\n" % (x, y + dy, z)
        out.append(l)
    open(obj, "w").writelines(out)


def extract(arc, out, prefix=None):
    """the whole archive (or its entries under prefix) as <out>/<entry path>.<class> (the layout mod2obj resolves
    textures in)."""
    data = open(arc, "rb").read()
    for name, th, cs, ds, _fl, off in arcx.entries(data):
        if prefix and not name.lower().startswith(prefix):
            continue
        raw = zlib.decompress(data[off:off + cs]) if cs != ds else data[off:off + cs]
        p = os.path.join(out, *name.split("\\")) + "." + TYPES.get(th, f"0x{th:08x}")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(raw)
    return data


def tables():
    """the add-on's id tables, read without bpy (literal assignments only)."""
    import ast, types
    src = open(os.path.join(HERE, "blender_lp2_map_markers.py")).read()
    t = types.SimpleNamespace()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
                "VS_TYPES", "PICKUPS", "VS_WEAPONS", "SLOTS", "POSTS"):
            setattr(t, node.targets[0].id, ast.literal_eval(node.value))
    return t


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    auto = os.path.join(sys.argv[1], "nativePC", "arcLp2Xml", "autoArc")
    out = os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    A = tables()
    jobs = [("Vs", "vs", f"{v[0]:02x}", f"vs_{v[0]:02x}") for v in A.VS_TYPES]
    fixed = sorted({w for w, _ in A.PICKUPS} | set(A.VS_WEAPONS))
    # VS weapons 41 / 43 / 44 have empty archives (listed as slots) but a model in aPowerOn
    jobs += [("Wp", "wp", f"{w:02x}", f"wp_{w:02x}") for w in fixed if w not in A.SLOTS or w in A.VS_WEAPONS]
    jobs += [("Om", "om", p[1][2:], f"om_{p[1][2:]}") for p in A.POSTS]
    manifest = {}
    if sys.argv[3:]:
        jobs = [j for j in jobs if j[3] in sys.argv[3:]]
        if os.path.exists(os.path.join(out, "manifest.json")):
            manifest = json.load(open(os.path.join(out, "manifest.json")))
    for prefix, kind, tag, key in jobs:
        arc = find_arc(auto, prefix, tag)
        common = os.path.join(os.path.dirname(os.path.dirname(auto)), "arcXmlTmpPC", "aPowerOn.arc")
        if kind == "wp" and (not arc or os.path.getsize(arc) < 1024):
            arc = common   # the model lives in the always-loaded archive (extracted below by its own folder only)
        if not arc or os.path.getsize(arc) < 1024:
            print(f"{key}: no archive / slot, skipped")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            own = f"model\\{kind}\\{kind}{tag}\\"
            data = extract(arc, tmp, own if arc == common else None)
            model = pick_model(data, kind, tag)
            if arc == common and not (model or "").lower().startswith(own):
                model = None   # only its own folder was extracted: another weapon's model isn't this one's
            if kind == "wp" and arc != common and not (model or "").lower().startswith(own):
                # some VS weapons keep their model in the always-loaded aPowerOn archive
                if os.path.exists(common):
                    data = extract(common, tmp, own)
                    m2 = pick_model(data, kind, tag)
                    model = m2 if (m2 or "").lower().startswith(own) else model
            if not model:
                print(f"{key}: no model in {os.path.basename(arc)}")
                continue
            subprocess.run([sys.executable, os.path.join(HERE, "tex2dds.py"), "-r", tmp], check=True, capture_output=True)
            dst = os.path.join(out, key)
            os.makedirs(dst, exist_ok=True)
            leaf = model.split("\\")[-1]
            src = os.path.join(tmp, *model.split("\\")) + ".rModel"
            pose = []
            mot = pick_motions(data, kind) if kind == "vs" else None
            if mot:
                pose = ["--pose", os.path.join(tmp, *mot.split("\\")) + ".rMotionList:0"]
            obj = os.path.join(dst, leaf + ".obj")
            one = ["--one-copy"] if kind == "wp" else []   # VS weapons: one copy per mount in the model
            subprocess.run([sys.executable, os.path.join(HERE, "mod2obj.py"), src, obj] + pose + one, check=True, capture_output=True)
            if kind == "vs" and lowest(obj) < -60:
                # motion 0 isn't a standing idle for this type (flying, bosses, a few odd ones): bind pose, lowest point
                # on the floor
                if pose:
                    subprocess.run([sys.executable, os.path.join(HERE, "mod2obj.py"), src, obj], check=True, capture_output=True)
            if kind == "vs" and lowest(obj) < 0:  # legs stay straight without the game's IK: feet onto the floor
                lift(obj, -lowest(obj))
            if kind == "wp" and lowest(obj) < 0:  # weapons have their origin mid-model: onto the floor
                lift(obj, -lowest(obj))
            # copy the textures the MTL names next to the OBJ, rewrite paths to plain names
            mtl = os.path.join(dst, leaf + ".mtl")
            lines = []
            for line in open(mtl):
                if line.startswith("map_Kd "):
                    rel = line.split(" ", 1)[1].strip()
                    p = os.path.normpath(os.path.join(dst, rel))
                    if os.path.exists(p):
                        name = os.path.basename(p)
                        open(os.path.join(dst, name), "wb").write(open(p, "rb").read())
                        line = f"map_Kd {name}\n"
                lines.append(line)
            open(mtl, "w").writelines(lines)
            manifest[key] = os.path.join(key, leaf + ".obj")
            print(f"{key}: {model}")
    if "om_7100" not in manifest and "om_7103" in manifest:  # uOm7100 has no model; the posts share om7103
        manifest["om_7100"] = manifest["om_7103"]
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    print(f"{len(manifest)} models -> {out}")


if __name__ == "__main__":
    main()
