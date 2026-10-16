#!/usr/bin/env python3
"""Build an overlay mod that puts a copy of an online map into a free map slot (13 or 14).

  mapslot.py --game GAMEDIR --src 0 --slot 13 --name "Test Arena" [--tint highlight] MODDIR

Writes MODDIR (an overlay folder for xlive.dll's "mods" -> "enabled" list):
  mod.json                                      {"maps": [{"slot", "base", "name"}]}; the DLL
                                                makes the slot selectable and gives it the source
                                                map's preload list
  nativePC/... aArea_ONLINE_<slot>*             the source map's files under the new number
  nativePC/arcLp2Xml/ID_FCORE_EN_PC.arc         MsgOnline with message 126+slot = the name
  nativePC/arcXmlTmpPC/aBattlePlayerCreate.arc  the create-session screen (flash\\playermatch\\id221)
                                                with a thumbnail in mc_monitor frame slot+2: a new
                                                external image ID221_SC<n>_ID plus its texture, a
                                                tinted copy of the source map's thumbnail

The Flash file is Scaleform GFx and is edited through JPEXS FFDec's XML export
(~/Applications/ffdec). Only English (ID_FCORE_EN_PC) gets the name for now.
"""
import argparse, copy, json, os, re, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcx, dlcpart, flashmsg  # noqa: E402

FFDEC = os.path.expanduser("~/Applications/ffdec/ffdec-cli.jar")
MSG_MAP = 126           # MsgOnline: map names are 126 + map id
PICKER_ARCS = ["arcXmlTmpPC/aBattlePlayerCreate.arc", "arcLp2Xml/ID_TITLE.arc", "arcLp2Xml/ID_TITLE_MULTI.arc"]
SC_INDEX = {**{m: m for m in range(13)}, 15: 13}  # map id -> ID221_SC<nn> thumbnail


def map_files(native, mid):
    """(relative path in nativePC, is_dir) of every file named after online map mid."""
    n = f"{mid:02d}"
    return [f"arcXmlTmpPC/aArea_ONLINE_{n}.arc", f"arcXmlTmpPC/variable/aArea_ONLINE_{n}_v.arc",
            f"arcLp2Xml/autoArc/aArea_ONLINE_{n}.arc", f"arcLp2Xml/autoArc/aArea_ONLINE_{n}_scr.arc",
            f"sa/DX9/Lost2/Game/Episode_ONLINE/Area_ONLINE_{n}", f"sa/DX11/Lost2/Game/Episode_ONLINE/Area_ONLINE_{n}",
            f"sound/bgm/aArea_ONLINE_{n}"]


# (archive, resource name with {:02d} for the map, class, loose-file extension)
BOOT_RESOURCES = [("arcXmlTmpPC/aPowerOn.arc", "detail\\windows\\aArea_ONLINE_{:02d}", "rTexDetailEdit", "tde"),
                  ("arcLp2Xml/ID_CORE_PC.arc", "MaterialSkipList\\aArea_ONLINE_{:02d}", "rMaterialSkipList", "msl"),
                  ("arcXmlTmpPC/aPowerOn.arc", "tool\\scrCollisionArea\\aArea_ONLINE_{:02d}", "rScrCollisionArea", "swc")]


# Names the game builds from the map number (area type 7 = online), renumbered in any case.
NUMBERED = [rb"area_online_", rb"rader_map_7_"]


def renumber(data, src, slot):
    """<prefix><src> -> <prefix><slot> for every NUMBERED prefix (same length, so offsets stay valid)."""
    for prefix in NUMBERED:
        data = re.sub(rb"(?i)(" + prefix + rb")" + f"{src:02d}".encode(), lambda m: m.group(1) + f"{slot:02d}".encode(), data)
    return data


def copy_renumbered(s, d, src, slot):
    """Copy a map file; archives get their entry names and contents renumbered, since the game
    looks several of the map's resources up by number (scheduler, scene box, BGM, spawns...)."""
    os.makedirs(os.path.dirname(d), exist_ok=True)
    if not s.lower().endswith(".arc"):
        shutil.copyfile(s, d)
        return
    work = tempfile.mkdtemp(prefix="lp2renum")
    try:
        order = extract(s, os.path.join(work, "in"))
        out_root = os.path.join(work, "out")
        os.makedirs(out_root, exist_ok=True)
        lines = []
        for name, cls in order:
            data = open(path_of(os.path.join(work, "in"), name, cls), "rb").read()
            new = renumber(name.encode("latin-1"), src, slot).decode("latin-1")
            p = path_of(out_root, new, cls)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(renumber(data, src, slot))
            lines.append(f"{new}\t{cls}\n")
        open(os.path.join(out_root, ".arcorder"), "w", encoding="latin-1").writelines(lines)
        arcx.pack(out_root, d)
    finally:
        shutil.rmtree(work)


def extract(arc, out):
    sys.argv = ["arcx", "x", arc, out]
    arcx.main()
    return [ln.rstrip("\n").split("\t") for ln in open(os.path.join(out, ".arcorder"), encoding="latin-1")]


def path_of(root, name, cls):
    return os.path.join(root, *name.split("\\")) + "." + cls


def add_to_resource_list(path, name, cls):
    """Append (name, class) to an ARCS resource list (the textures a Flash screen loads with it).
    Layout: 'ARCS' u16 8 u16 count, then count x (u32 crc32(name)^~0, u32 class hash)."""
    import struct, zlib
    b = bytearray(open(path, "rb").read())
    if b[:4] != b"ARCS":
        raise SystemExit(f"{path}: not an ARCS list")
    n = struct.unpack_from("<H", b, 6)[0]
    entry = struct.pack("<II", zlib.crc32(name.encode("latin-1")) ^ 0xFFFFFFFF, arcx.class_hash(cls))
    b[8 + 8 * n:8 + 8 * n] = entry
    struct.pack_into("<H", b, 6, n + 1)
    open(path, "wb").write(bytes(b))


def edit_gfx(gfx_in, gfx_out, slot, work):
    """Add external image ID221_SC<n>_ID and show it in mc_monitor's frame for map `slot`."""
    sc = 14 + (slot - 13)  # SC00-13 are taken by maps 0-12 and 15
    xml_in, xml_out = os.path.join(work, "in.xml"), os.path.join(work, "out.xml")
    subprocess.run(["java", "-jar", FFDEC, "-swf2xml", gfx_in, xml_in], check=True, capture_output=True)
    tree = ET.parse(xml_in)
    tags = tree.getroot().find("tags")
    items = list(tags)

    def cid(it):
        for k in ("shapeId", "spriteId", "characterID", "characterId", "fontId", "buttonId"):
            if it.get(k):
                return int(it.get(k))
        return 0
    new_img, new_shape = max(cid(it) for it in items) + 1, max(cid(it) for it in items) + 2
    # The monitor clip is the sprite placed with name mc_monitor; its frame 2 shows map 0.
    mon_id = next(it.get("characterId") for it in tree.iter("item") if it.get("name") == "mc_monitor")
    sprite = next(it for it in items if it.get("type") == "DefineSpriteTag" and it.get("spriteId") == mon_id)
    sub = list(sprite.find("subTags"))
    frames, cur = [[]], 0
    for st in sub:
        frames[cur].append(st)
        if st.get("type") == "ShowFrameTag":
            frames.append([])
            cur += 1
    first = next(st for st in frames[1] if st.get("type") == "PlaceObject2Tag")  # map 0
    shape0 = next(it for it in items if it.get("type") == "DefineShapeTag" and it.get("shapeId") == first.get("characterId"))
    img0_id = next(f.get("bitmapId") for f in shape0.iter("item") if f.get("bitmapId") not in (None, "65535"))
    img0 = next(it for it in items if it.get("type") == "DefineExternalImage" and it.get("characterID") == img0_id)

    img = copy.deepcopy(img0)
    img.set("characterID", str(new_img))
    img.set("exportName", f"ID221_SC{sc:02d}_ID")
    # FFDec's XML escapes backslashes, so the stored path ..\dds\X.dds is written doubled.
    img.set("fileName", img0.get("fileName").replace(img0.get("exportName"), f"ID221_SC{sc:02d}_ID"))
    shape = copy.deepcopy(shape0)
    shape.set("shapeId", str(new_shape))
    for f in shape.iter("item"):
        if f.get("bitmapId") == img0_id:
            f.set("bitmapId", str(new_img))
    pos = items.index(sprite)
    tags.insert(pos, shape)
    tags.insert(pos, img)

    # Frame index for map `slot` is slot+1 (0-based list; frame 1 is the 'stop' frame).
    fr = frames[slot + 1]
    action = next(st for st in frames[1] if st.get("type") == "DoActionTag")  # map 0's size text
    place = copy.deepcopy(first)
    place.set("characterId", str(new_shape))
    keep = [st for st in fr if st.get("type") in ("RemoveObject2Tag",)]
    new_frame = keep + [copy.deepcopy(action), place] + [st for st in fr if st.get("type") == "ShowFrameTag"]
    # The next frame must clear our thumbnail before showing (or not showing) its own.
    nxt = frames[slot + 2]
    if not any(st.get("type") == "RemoveObject2Tag" for st in nxt):
        rm = copy.deepcopy(next(st for f2 in frames for st in f2 if st.get("type") == "RemoveObject2Tag"))
        nxt.insert(0, rm)
    frames[slot + 1] = new_frame
    st_el = sprite.find("subTags")
    for st in list(st_el):
        st_el.remove(st)
    for f2 in frames:
        for st in f2:
            st_el.append(st)
    tree.write(xml_out, encoding="utf-8", xml_declaration=True)
    subprocess.run(["java", "-jar", FFDEC, "-xml2swf", xml_out, gfx_out], check=True, capture_output=True)
    return sc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, help="the Lost Planet 2 folder")
    ap.add_argument("--src", type=int, required=True, help="online map to copy (0-12, 15)")
    ap.add_argument("--slot", type=int, required=True, choices=(13, 14))
    ap.add_argument("--name", required=True)
    ap.add_argument("--size", choices=("small", "medium", "large"),
                    help="map size class for the lobby and Random <size> (default: the source map's)")
    ap.add_argument("--tint", default="highlight", choices=sorted(dlcpart.TINTS))
    ap.add_argument("out")
    a = ap.parse_args()
    native = os.path.join(a.game, "nativePC")
    dst = os.path.join(a.out, "nativePC")

    for rel_src, rel_dst in zip(map_files(native, a.src), map_files(native, a.slot)):
        s, d = os.path.join(native, rel_src), os.path.join(dst, rel_dst)
        if os.path.isdir(s):
            for dd, _, fs in os.walk(s):
                for fn in fs:
                    copy_renumbered(os.path.join(dd, fn), os.path.join(d, os.path.relpath(os.path.join(dd, fn), s)), a.src, a.slot)
        elif os.path.exists(s):
            copy_renumbered(s, d, a.src, a.slot)
        else:
            print("missing (skipped):", rel_src)
            continue
        print(f"{rel_src} -> {rel_dst}")

    # Per-map resources kept in boot archives; the game falls back to loose <name>.<ext> files.
    for arc, name, cls, ext in BOOT_RESOURCES:
        work1 = tempfile.mkdtemp(prefix="lp2boot")
        try:
            extract(os.path.join(native, arc), work1)
            p = path_of(work1, name.format(a.src), cls)
            out = os.path.join(dst, *name.format(a.slot).split("\\")) + "." + ext
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(renumber(open(p, "rb").read(), a.src, a.slot))
            print(f"{arc}:{name.format(a.src)} -> loose {os.path.relpath(out, dst)}")
        finally:
            shutil.rmtree(work1)

    work = tempfile.mkdtemp(prefix="lp2map")
    try:
        # Name.
        arc = "arcLp2Xml/ID_FCORE_EN_PC.arc"
        root = os.path.join(work, "fcore")
        order = extract(os.path.join(native, arc), root)
        p = path_of(root, "message\\msgPC\\MsgOnline", "rFlashMessage")
        data = flashmsg.set_message(open(p, "rb").read(), MSG_MAP + a.slot, a.name)
        open(p, "wb").write(data)
        os.makedirs(os.path.dirname(os.path.join(dst, arc)), exist_ok=True)
        arcx.pack(root, os.path.join(dst, arc))
        print(f"{arc}: MsgOnline {MSG_MAP + a.slot} = {a.name!r}")

        # Thumbnail: the picker is in the create-session archive and also in the title archives
        # loaded at boot (whichever copy loads first is the one the screen uses), so all get it.
        for k, arc in enumerate(PICKER_ARCS):
            root = os.path.join(work, f"picker{k}")
            extract(os.path.join(native, arc), root)
            flash = path_of(root, "flash\\playermatch\\id221", "rFlash")
            gfx_in, gfx_out = os.path.join(work, "in.gfx"), os.path.join(work, "out.gfx")
            shutil.copyfile(flash, gfx_in)
            sc = edit_gfx(gfx_in, gfx_out, a.slot, work)
            shutil.copyfile(gfx_out, flash)
            src_tex = path_of(root, f"flash\\dds\\ID221_SC{SC_INDEX[a.src]:02d}_ID", "rTexture")
            new_name = f"flash\\dds\\ID221_SC{sc:02d}_ID"
            tex = dlcpart.tint_texture(open(src_tex, "rb").read(), a.tint)
            open(path_of(root, new_name, "rTexture"), "wb").write(tex)
            with open(os.path.join(root, ".arcorder"), "a", encoding="latin-1") as f:
                f.write(f"{new_name}\trTexture\n")
            add_to_resource_list(path_of(root, "flash\\playermatch\\id221", "rArchive"), new_name, "rTexture")
            os.makedirs(os.path.dirname(os.path.join(dst, arc)), exist_ok=True)
            arcx.pack(root, os.path.join(dst, arc))
            print(f"{arc}: thumbnail {new_name} ({a.tint} copy of map {a.src}'s)")
    finally:
        shutil.rmtree(work)

    entry = {"slot": a.slot, "base": a.src, "name": a.name}
    if a.size:
        entry["size"] = a.size
    json.dump({"maps": [entry]},
              open(os.path.join(a.out, "mod.json"), "w"), indent=1)
    print("wrote", os.path.join(a.out, "mod.json"))


if __name__ == "__main__":
    main()
