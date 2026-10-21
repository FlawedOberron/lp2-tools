#!/usr/bin/env python3
"""Game models for the Blender map markers (blender_lp2_map_markers.py): every VS type, the fixed weapons
and the data posts, as OBJ + DDS, then (blender_marker_assets.py) one lp2_marker_assets.blend.

  build_marker_assets.py GAME_DIR OUT_DIR

GAME_DIR: the Lost Planet 2 folder. Each type's archive is nativePC/arcLp2Xml/autoArc/u<Vs|Wp|Om><id>.arc;
its model = the largest rModel in the type's own folder (model/vs/vsXX/, model/wp/wpXX/, model/om/omXXXX/),
else the largest one under model/vs|wp|om/ (types that borrow another folder's model, e.g. 0x53 -> vs03).
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
    own, other = [], []
    for name, th, cs, ds, _fl, _off in arcx.entries(data):
        if TYPES.get(th) != "rModel":
            continue
        low = name.lower()
        if low.startswith(f"model\\{kind}\\{kind}{tag}\\"):
            own.append((ds, name))
        elif low.startswith(f"model\\{kind}\\"):
            other.append((ds, name))
    return max(own or other or [(0, None)])[1]


def extract(arc, out):
    """the whole archive as <out>/<entry path>.<class> (the layout mod2obj resolves textures in)."""
    data = open(arc, "rb").read()
    for name, th, cs, ds, _fl, off in arcx.entries(data):
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
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    auto = os.path.join(sys.argv[1], "nativePC", "arcLp2Xml", "autoArc")
    out = os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    A = tables()
    jobs = [("Vs", "vs", f"{v[0]:02x}", f"vs_{v[0]:02x}") for v in A.VS_TYPES]
    fixed = sorted({w for w, _ in A.PICKUPS} | set(A.VS_WEAPONS))
    jobs += [("Wp", "wp", f"{w:02x}", f"wp_{w:02x}") for w in fixed if w not in A.SLOTS]
    jobs += [("Om", "om", p[1][2:], f"om_{p[1][2:]}") for p in A.POSTS]
    manifest = {}
    for prefix, kind, tag, key in jobs:
        arc = find_arc(auto, prefix, tag)
        if not arc or os.path.getsize(arc) < 1024:
            print(f"{key}: no archive / slot, skipped")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            data = extract(arc, tmp)
            model = pick_model(data, kind, tag)
            if not model:
                print(f"{key}: no model in {os.path.basename(arc)}")
                continue
            subprocess.run([sys.executable, os.path.join(HERE, "tex2dds.py"), "-r", tmp], check=True, capture_output=True)
            dst = os.path.join(out, key)
            os.makedirs(dst, exist_ok=True)
            leaf = model.split("\\")[-1]
            src = os.path.join(tmp, *model.split("\\")) + ".rModel"
            subprocess.run([sys.executable, os.path.join(HERE, "mod2obj.py"), src, os.path.join(dst, leaf + ".obj")], check=True, capture_output=True)
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
