#!/usr/bin/env python3
"""Lost Planet 1 character survey (PC nativePC, or the 360 Colonies nativeXenon tree from xiso.py):
pull every human model (model\\hm\\hmXX) out of the LP1 archives, convert each to OBJ (lp1model.py) and render a preview, then a labelled contact sheet.
  lp1chars.py [--kind vs] LP1_NATIVEPC OUT_DIR [hm00 hm60 ...]      (default: every code found)
--kind: the model folder to survey (hm characters, the default; vs the VS: model\\vs\\vsXX\\vsXX).
Needs: flatpak Blender (blender_preview.py) and ImageMagick `montage`.
"""
import glob, os, re, subprocess, sys, zlib
import arcx, lp1model

KIND = "hm"

HERE = os.path.dirname(os.path.abspath(__file__))


def scan(native):
    """-> {code: arc path} for the first archive holding model\\KIND\\code\\code."""
    found = {}
    for arc in sorted(glob.glob(os.path.join(native, "**", "*.arc"), recursive=True)):
        data = open(arc, "rb").read()
        for name, *_ in arcx.entries(data):
            m = re.fullmatch(rf"model\\{KIND}\\({KIND}\w+)\\(\w+)", name, re.I)  # the 360 has Hm70\Hm70
            if m and m.group(1).lower() == m.group(2).lower():
                found.setdefault(m.group(1).lower(), arc)
    return found


def extract(arc, code, out):
    data = open(arc, "rb").read()
    for name, th, cs, ds, _flags, off in arcx.entries(data):
        if name.lower().startswith(f"model\\{KIND}\\{code}\\"):
            raw = zlib.decompress(data[off:off + cs]) if cs != ds else data[off:off + cs]
            dst = os.path.join(out, *name.lower().split("\\")) + f".{th:#010x}"  # lower case: names differ in case
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(raw)


def main():
    global KIND
    argv = sys.argv[1:]
    if argv[:1] == ["--kind"]:
        KIND, argv = argv[1], argv[2:]
    if len(argv) < 2:
        raise SystemExit(__doc__)
    native, out = argv[0], os.path.abspath(argv[1])
    found = scan(native)
    codes = argv[2:] or sorted(found)
    tree, pngs = os.path.join(out, "tree"), []
    for code in codes:
        if code not in found:
            print(f"{code}: not found")
            continue
        extract(found[code], code, tree)
        model = os.path.join(tree, "model", KIND, code, f"{code}.0x1041bd9e")  # (extract lower-cases)
        d = os.path.join(out, code)
        os.makedirs(d, exist_ok=True)
        try:
            meshes, nv = lp1model.export_obj(model, os.path.join(d, f"{code}.obj"))
        except Exception as e:  # keep surveying; report the odd ones
            print(f"{code} ({os.path.basename(found[code])}): {e}")
            continue
        png = os.path.join(out, f"{code}.png")
        subprocess.run(["flatpak", "run", f"--filesystem={out}", "org.blender.Blender", "-b", "--python",
                        os.path.join(HERE, "blender_preview.py"), "--", os.path.join(d, f"{code}.obj"), png],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(png):
            pngs.append((code, os.path.basename(found[code]), png))
            print(f"{code} ({os.path.basename(found[code])}): {meshes} meshes, {nv} vertices")
    if pngs:
        args = []
        for code, arc, png in pngs:
            args += ["-label", f"{code}  {arc[:-4]}", png]
        subprocess.run(["montage", *args, "-tile", "8x", "-geometry", "256x256+3+3", "-background", "#333",
                        "-fill", "white", "-pointsize", "16", os.path.join(out, "sheet.png")], check=True)


if __name__ == "__main__":
    main()
