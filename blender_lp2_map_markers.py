# SPDX-License-Identifier: MIT
"""Lost Planet 2 map markers: spawn points, VS (with weapon mounts), weapon pickups and data posts.

Blender: Edit > Preferences > Add-ons > Install from Disk (this file), enable "LP2 Map Markers".
3D View > Sidebar (N) > "LP2 Map". Markers go into "LP2 Layout" > "Variant N" (the map's layout
variants -00 .. -03). "Export Layout" writes the JSON that lp2-tools/lp2layout.py builds the map's
rInitPosSet / rObjSet files from.

Space: LP2 is centimetres, Y up; Blender gets (x, -z, y) * scale (0.01 = metres, as the blend_maps files).
A marker faces Blender -Y at rotation 0 (LP2 direction 0); its Z rotation is the LP2 direction in degrees.
"""
bl_info = {
    "name": "LP2 Map Markers",
    "author": "lp2-tools",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar > LP2 Map",
    "description": "Place Lost Planet 2 spawns, VS, weapons and data posts; export a layout for lp2layout.py",
    "category": "Import-Export",
}

import json, math, os
import bpy
from mathutils import Matrix, Vector

VS_TYPES = [  # (type id, model, size m (x, y up, z), flying) from notes/vs-ids.md
    (0x00, "vs00", (7.2, 5.0, 2.6), False),
    (0x01, "vs01", (3.2, 5.3, 2.9), False),
    (0x02, "vs02", (2.2, 1.2, 3.4), False),
    (0x03, "om0014", (0.7, 0.4, 0.2), False),
    (0x04, "vs04", (3.2, 4.4, 3.4), False),
    (0x05, "vs05", (3.1, 4.4, 3.3), False),
    (0x06, "vs06", (0.6, 1.2, 0.8), False),
    (0x07, "vs07", (10.4, 4.9, 2.5), False),
    (0x13, "vs13", (2.3, 7.3, 3.5), False),
    (0x16, "vs16", (1.7, 1.5, 2.8), False),
    (0x20, "vs06", (1.7, 1.3, 3.8), False),
    (0x21, "vs16", (1.9, 1.8, 2.7), False),
    (0x22, "vs05", (3.1, 4.3, 3.3), False),
    (0x23, "vs04", (3.2, 4.5, 3.5), False),
    (0x24, "vs01", (3.1, 5.4, 2.9), False),
    (0x25, "vs00", (8.2, 5.0, 2.6), False),
    (0x26, "vsc6", (2.2, 2.9, 1.9), False),
    (0x27, "vsc3", (2.9, 4.3, 4.5), False),
    (0x28, "vscb", (10.7, 6.7, 9.6), False),
    (0x29, "vs03", (2.3, 7.3, 3.5), False),
    (0x2a, "vsce", (9.6, 5.4, 3.5), False),
    (0x2b, "vs32", (4.4, 4.9, 5.0), False),
    (0x2c, "vs34", (3.0, 4.7, 3.3), False),
    (0x2d, "vscf", (1.6, 2.5, 2.1), False),
    (0x2e, "vsc7", (1.6, 3.2, 1.7), False),
    (0x2f, "vsc8", (1.6, 3.2, 1.7), False),
    (0x30, "vs30", (2.7, 5.4, 2.9), False),
    (0x31, "vs31", (3.2, 4.5, 3.4), False),
    (0x32, "vs32", (4.1, 4.8, 4.4), False),
    (0x33, "vs33", (2.5, 7.3, 3.4), False),
    (0x34, "vs34", (3.0, 4.7, 3.3), False),
    (0x38, "vsc9", (1.8, 2.9, 1.9), False),
    (0x39, "vsc9", (1.8, 2.9, 1.9), False),
    (0x3a, "vsc9", (1.8, 2.9, 1.9), False),
    (0x3b, "vsc9", (1.8, 2.9, 1.9), False),
    (0x40, "vs40", (4.0, 4.8, 4.2), False),
    (0x41, "vs41", (14.7, 6.0, 5.6), False),
    (0x42, "vs42", (28.4, 19.6, 7.8), False),
    (0x43, "vs43", (20.4, 14.2, 5.6), False),
    (0x44, "vs44", (2.4, 7.6, 3.6), False),
    (0x45, "vs45", (7.6, 5.0, 2.6), False),
    (0x46, "vs46", (7.6, 5.0, 2.6), False),
    (0x50, "vs50", (7.2, 4.9, 2.6), False),
    (0x51, "vs51", (2.7, 5.4, 2.9), False),
    (0x53, "vs03", (2.4, 7.4, 3.4), False),
    (0x54, "vs04", (3.2, 4.4, 3.4), False),
    (0x55, "vs55", (3.0, 4.3, 3.1), False),
    (0x56, "vs56", (1.9, 2.7, 2.4), False),
    (0x66, "vs66", (1.9, 2.7, 2.2), False),
    (0x70, "vs06", (1.7, 1.3, 3.8), False),
    (0x71, "vs16", (1.9, 1.8, 2.7), False),
    (0x72, "vs05", (3.1, 4.3, 3.3), False),
    (0x73, "vs04", (3.2, 4.5, 3.5), False),
    (0x74, "vs01", (3.1, 5.4, 2.9), False),
    (0x75, "vs00", (8.2, 5.0, 2.6), False),
    (0x76, "vsc6", (2.2, 2.9, 1.9), False),
    (0x77, "vsc3", (2.9, 4.3, 4.5), False),
    (0x78, "vscb", (10.7, 6.7, 9.6), True),
    (0x79, "vs03", (2.3, 7.3, 3.5), False),
    (0x7a, "vsce", (9.6, 5.4, 3.5), False),
    (0x7b, "vs32", (4.4, 4.9, 5.0), False),
    (0x7c, "vs34", (3.0, 4.7, 3.3), False),
    (0x7d, "vscf", (1.6, 2.5, 2.1), False),
    (0x7e, "vsc7", (1.6, 3.2, 1.7), False),
    (0x7f, "vsc8", (1.6, 3.2, 1.7), False),
    (0x80, "vs80", (2.7, 5.4, 2.9), False),
    (0x81, "vs81", (3.2, 4.5, 3.4), False),
    (0x82, "vs82", (4.6, 4.7, 4.2), False),
    (0x84, "vs84", (2.9, 4.7, 3.4), False),
    (0x90, "vs06", (1.7, 1.3, 3.8), False),
    (0x91, "vs16", (1.9, 1.8, 2.7), False),
    (0x92, "vs05", (3.1, 4.3, 3.3), False),
    (0x93, "vs04", (3.2, 4.5, 3.5), False),
    (0x94, "vs01", (3.1, 5.4, 2.9), False),
    (0x95, "vs00", (8.2, 5.0, 2.6), False),
    (0x96, "vsc6", (2.2, 2.9, 1.9), False),
    (0x97, "vsc3", (2.9, 4.3, 4.5), False),
    (0x98, "vscb", (10.7, 6.7, 9.6), False),
    (0x99, "vs03", (2.3, 7.3, 3.5), False),
    (0x9a, "vsce", (9.6, 5.4, 3.5), False),
    (0x9b, "vs32", (4.4, 4.9, 5.0), False),
    (0x9c, "vs34", (3.0, 4.7, 3.3), False),
    (0x9d, "vscf", (1.6, 2.5, 2.1), False),
    (0x9e, "vsc7", (1.6, 3.2, 1.7), False),
    (0x9f, "vsc8", (1.6, 3.2, 1.7), False),
    (0xa0, "vs06", (1.7, 1.3, 3.8), False),
    (0xa2, "vs05", (3.1, 4.3, 3.3), False),
    (0xa3, "vs04", (3.2, 4.5, 3.5), False),
    (0xa4, "vs01", (3.1, 5.4, 2.9), False),
    (0xa5, "vs00", (8.2, 5.0, 2.6), False),
    (0xa6, "vsc6", (2.2, 2.9, 1.9), False),
    (0xa7, "vsc3", (2.9, 4.3, 4.5), False),
    (0xa8, "vscb", (10.7, 6.7, 9.6), True),
    (0xa9, "vs03", (2.3, 7.3, 3.5), False),
    (0xaa, "vsce", (9.6, 5.4, 3.5), False),
    (0xae, "vsc7", (1.6, 3.2, 1.7), False),
    (0xaf, "vsc8", (1.6, 3.2, 1.7), False),
    (0xc1, "vsc1", (18.6, 12.9, 82.4), False),
    (0xc2, "vsc2", (3.3, 2.3, 5.3), False),
    (0xcb, "vscb", (10.7, 6.9, 10.2), False),
    (0xcd, "vscd", (9.2, 10.9, 21.1), False),
    (0xce, "sh33", (0.1, 0.2, 0.8), False),
    (0xd0, "vsd0", (2.7, 2.9, 3.0), False),
    (0xd5, "vsd5", (2.0, 1.5, 1.9), False),
    (0xd6, "vsd6", (2.8, 1.5, 3.9), False),
    (0xd7, "vsd7", (1.7, 3.6, 1.7), False),
    (0xe0, "vse0", (3.5, 2.0, 3.5), False),
    (0xe1, "vse1", (13.1, 16.7, 30.9), False),
    (0xe3, "vse3", (2.8, 3.9, 4.6), False),
    (0xe4, "vse4", (3.5, 4.7, 3.5), False),
    (0xe9, "vsc4", (2.0, 2.4, 2.4), False),
    (0xea, "vsc5", (2.0, 3.0, 2.7), False),
    (0xeb, "vsc4", (2.0, 2.4, 2.4), False),
    (0xec, "vsc5", (2.0, 3.0, 2.7), False),
    (0xed, "vsc4", (2.0, 2.4, 2.4), False),
    (0xee, "vsc5", (2.0, 3.0, 2.7), False),
    (0xf4, "vscd", (9.2, 10.9, 21.1), False),
    (0xf8, "vsc4", (2.0, 2.4, 2.4), False),
    (0xf9, "vsc5", (2.0, 3.0, 2.7), False),
    (0xda, "vscb", (10.7, 6.7, 9.6), True),  # model folder vs78 (as 0x78 / 0xa8); size assumed
    (0x1a, "ak00", (2.9, 10.5, 9.4), False),
    (0x1b, "om8600", (2.7, 2.0, 4.9), False),
    (0x1c, "om86ff", (16.3, 5.3, 19.9), False),
    (0xa1, "vs16", (1.9, 1.8, 2.7), False),
    (0xab, "vs32", (4.4, 4.9, 5.0), False),
    (0xac, "vs34", (3.0, 4.7, 3.3), False),
    (0xad, "vscf", (1.6, 2.5, 2.1), False),
    (0xb9, "vsb9", (18.1, 8.7, 77.6), False),
    (0xba, "vsba", (5.2, 6.1, 10.8), False),
    (0xbf, "vs34", (3.0, 4.7, 3.3), False),
    (0xc3, "vsc3", (3.0, 4.4, 4.3), False),
    (0xc4, "vsc4", (2.0, 2.4, 2.4), False),
    (0xc5, "vsc5", (2.0, 3.0, 2.7), False),
    (0xc6, "vsc6", (2.4, 3.0, 2.1), False),
    (0xc7, "vsc7", (1.6, 3.2, 1.7), False),
    (0xc8, "vsc8", (1.6, 3.2, 1.7), False),
    (0xc9, "vsc9", (2.0, 3.0, 2.1), False),
    (0xca, "vsca", (20.8, 12.8, 82.4), False),
    (0xcc, "vscb", (10.7, 6.9, 10.2), False),
    (0xcf, "vscf", (1.6, 2.5, 2.1), False),
    (0xd4, "vsd4", (3.2, 3.2, 3.6), False),
    (0xd9, "vscb", (10.7, 6.7, 9.6), False),
    (0xdb, "vscb", (10.7, 6.7, 9.6), False),
    (0xdc, "vscb", (10.7, 6.7, 9.6), False),
    (0xe2, "vs04", (3.5, 4.8, 3.6), False),
    (0xe7, "vse7", (2.8, 3.9, 4.6), False),
    (0xe8, "vse8", (3.5, 4.7, 3.5), False),
    (0xef, "om825c", (7.8, 5.6, 17.7), False),
    (0xf0, "vs04", (3.5, 4.8, 3.6), False),
]

# Weapon pickups placed by the stock online maps (objset group 4 item ids, with how often they appear).
PICKUPS = [(0x15, 1182), (0x16, 942), (0x17, 1082), (0x18, 998), (0x19, 1039), (0x0c, 232), (0x1c, 176),
           (0x1d, 112), (0x1e, 106), (0x1f, 184), (0x20, 605), (0x21, 514), (0x22, 203), (0x23, 107),
           (0x30, 1346), (0x31, 1740), (0x32, 1590), (0x33, 1572), (0x34, 1095), (0x41, 332), (0x42, 240),
           (0x43, 371), (0x44, 400), (0x45, 235), (0x46, 248), (0x47, 195), (0x60, 219), (0x61, 257),
           (0x62, 120), (0x63, 562), (0x64, 184), (0x01, 1), (0x02, 2), (0x04, 2), (0x05, 3), (0x08, 2), (0x48, 1)]
# Slot ids: their uWpXX.arc is empty (0 KB), so the match settings pick the actual weapon (Standard, Short,
# Long, Heavy ...). SLOT_NAMES from the 2026-10-20 in-game slot test (row order); 0x41 / 0x43 / 0x44 gave
# no ground pickup: VS mount slots (stock VS records use them).
SLOTS = {0x0c, 0x15, 0x16, 0x17, 0x18, 0x19, 0x30, 0x31, 0x32, 0x33, 0x34, 0x41, 0x43, 0x44}
SLOT_NAMES = {0x0c: "Handgun", 0x15: "Frag grenade", 0x16: "Gum grenade", 0x17: "Disk grenade",
              0x18: "Dummy grenade", 0x19: "Plasma grenade", 0x30: "Standard", 0x31: "Short", 0x32: "Long",
              0x33: "Heavy", 0x34: "Special", 0x41: "VS weapon", 0x43: "VS weapon", 0x44: "VS weapon"}
# Weapons the stock VS records mount; 0x41 (a slot) is the usual default.
VS_WEAPONS = [0x41, 0x4e, 0x50, 0x4d, 0x42, 0x44, 0x60, 0x43, 0x62, 0x6d, 0x46, 0x45]
# objset +0x04: the stock maps split VS and weapons ~45/33/22 % over 0 / 10 / 20, the match's
# VS / weapon amount setting (None / Normal / Maximum); higher tiers presumably need higher settings.
TIERS = [("0", "Tier 0", "every amount setting but None (stock: ~45 %)"),
         ("10", "Tier 10", "higher amount settings (stock: ~33 %)"),
         ("20", "Tier 20", "Maximum only, presumably (stock: ~22 %)")]
# game types: lp2layout.py file name -> mode (TeamBattle/Team, KojinBattle/Slayer, FoxBattle/Fox ...)
MODE_ITEMS = [("team", "Team Elimination", "TeamBattle / Team files", 1), ("slayer", "Elimination", "KojinBattle / Slayer files", 2),
              ("datapost", "Data Post", "Datapost files", 4), ("fox", "Fugitive", "FoxBattle / Fox files", 8),
              ("egg", "Akrid Egg", "Egg files", 16), ("counter", "Counter", "Counter files (mode name unknown)", 32),
              ("vs", "VS", "VS files (mode name unknown)", 64)]
ALL_MODES = {m[0] for m in MODE_ITEMS}
# Data posts: objset group 3 objects om71xx (om7100 is in 599 of 640 stock layouts).
POSTS = [(0x0071, "om7100", "Data post"), (0x0371, "om7103", "Data post (variant 03)"), (0x1371, "om7113", "Data post (variant 13)")]

# role -> (label, LP2 rInitPosSet kind, colour)
SPAWN_ROLES = {
    "start": ("FFA start", 0, (0.95, 0.95, 0.95, 1)),
    "team_a": ("Team A", 1, (0.9, 0.2, 0.2, 1)),
    "team_b": ("Team B", 2, (0.2, 0.4, 0.95, 1)),
    "k30": ("Team A base", 6, (1.0, 0.55, 0.55, 1)),
    "k31": ("Team B base", 7, (0.55, 0.7, 1.0, 1)),
    "k40": ("Extra (kind 3)", 3, (0.6, 0.6, 0.6, 1)),
}
COLOURS = {"vs": (1.0, 0.55, 0.1, 1), "vs_fly": (0.7, 0.3, 0.95, 1), "weapon": (0.25, 0.85, 0.3, 1), "post": (0.1, 0.85, 0.85, 1)}
VS_BY_ID = {v[0]: v for v in VS_TYPES}
POSTS_BY_ITEM = {p[0]: p for p in POSTS}


def hexid(v):
    return f"0x{v:02x}"


VS_ITEMS = [(hexid(v[0]), f"{hexid(v[0])} {v[1]}" + (" (flies)" if v[3] else ""),
             f"{v[1]}: {v[2][0]} x {v[2][1]} x {v[2][2]} m", i) for i, v in enumerate(sorted(VS_TYPES))]


def weapon_label(w):
    if w in SLOTS:
        return f"{hexid(w)} slot" + (f": {SLOT_NAMES[w]}" if w in SLOT_NAMES else "")
    return f"{hexid(w)} fixed"


# slots first: they follow the match's weapon settings like the stock maps
PICKUP_ITEMS = [(hexid(w), weapon_label(w), f"{'slot (match settings pick the weapon)' if w in SLOTS else 'fixed weapon'}, "
                 f"placed {n}x in stock maps", i) for i, (w, n) in enumerate(sorted(PICKUPS, key=lambda x: (x[0] not in SLOTS, x[0])))]
VS_WEAPON_ITEMS = [(hexid(w), weapon_label(w) + (" (default)" if w == 0x41 else ""), "VS weapon mount", i) for i, w in enumerate(VS_WEAPONS)]
POST_ITEMS = [(hexid(p[0]), f"{p[1]} {p[2]}", p[2], i) for i, p in enumerate(POSTS)]


# ---------------------------------------------------------------- meshes and materials

def box(x0, x1, y0, y1, z0, z1, base=0):
    v = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return v, [tuple(i + base for i in q) for q in f]


def arrow(length, width, z, base=0):
    """flat arrow on the ground pointing -Y (LP2 forward)."""
    v = [(-width, 0, z), (width, 0, z), (0, -length, z)]
    return v, [(base, base + 2, base + 1)]


def build(parts):
    verts, faces = [], []
    for fn, args in parts:
        v, f = fn(*args, base=len(verts))
        verts += v
        faces += f
    return verts, faces


def asset_library():
    try:
        path = bpy.context.preferences.addons[__name__].preferences.library
    except (KeyError, AttributeError):
        path = ""
    for p in (bpy.path.abspath(path) if path else "", os.path.join(os.path.dirname(__file__), "lp2_marker_assets.blend")):
        if p and os.path.isfile(p):
            return p
    return None


def asset_mesh(key, scale):
    """the game model for a marker key (vs_66, wp_42, om_7100) from lp2_marker_assets.blend, or None."""
    name = f"LP2 asset {key} @{scale:g}"
    me = bpy.data.meshes.get(name)
    if me:
        return me
    lib = asset_library()
    if not lib:
        return None
    src = f"LP2 asset {key}"
    with bpy.data.libraries.load(lib, link=False) as (data_from, data_to):
        if src not in data_from.meshes:
            return None
        data_to.meshes = [src]
    me = data_to.meshes[0]
    me.name = name
    if abs(scale - 0.01) > 1e-9:  # the library is in metres (scale 0.01)
        me.transform(Matrix.Scale(scale / 0.01, 4))
    return me


def marker_mesh(key, scale):
    name = f"LP2 {key} @{scale:g}"
    me = bpy.data.meshes.get(name)
    if me:
        return me
    m = scale * 100  # metres -> blender units
    if key.startswith("spawn"):
        parts = [(box, (-0.25 * m, 0.25 * m, -0.15 * m, 0.15 * m, 0, 1.8 * m)), (arrow, (1.2 * m, 0.4 * m, 0.02 * m))]
    elif key.startswith("vs_"):
        sx, sy, sz = VS_BY_ID[int(key[3:], 16)][2]
        parts = [(box, (-sx / 2 * m, sx / 2 * m, -sz / 2 * m, sz / 2 * m, 0, sy * m)),
                 (arrow, (sz / 2 * m + 1.0 * m, 0.6 * m, 0.03 * m))]
    elif key.startswith("weapon"):
        parts = [(box, (-0.3 * m, 0.3 * m, -0.3 * m, 0.3 * m, 0, 0.1 * m)), (box, (-0.07 * m, 0.07 * m, -0.6 * m, 0.6 * m, 0.4 * m, 0.6 * m))]
    else:  # post
        parts = [(box, (-0.25 * m, 0.25 * m, -0.25 * m, 0.25 * m, 0, 3.0 * m)), (box, (-0.6 * m, 0.6 * m, -0.6 * m, 0.6 * m, 3.0 * m, 3.2 * m))]
    v, f = build(parts)
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.update()
    return me


def material(key, colour):
    name = f"LP2 {key}"
    mat = bpy.data.materials.get(name)
    if not mat:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = colour
    return mat


def refresh(ob, context=None):
    """mesh, material and name from the marker settings."""
    p = ob.lp2
    scale = bpy.context.scene.lp2_scale
    if p.marker == "SPAWN":
        label, _, col = SPAWN_ROLES[p.spawn_role]
        key, matkey, nm = "spawn", "spawn " + p.spawn_role, f"Spawn {label}"
    elif p.marker == "VS":
        vid = int(p.vs_type, 16)
        fly = VS_BY_ID[vid][3]
        key, matkey, nm, col = f"vs_{vid:02x}", "vs_fly" if fly else "vs", f"VS {p.vs_type} {VS_BY_ID[vid][1]}", COLOURS["vs_fly" if fly else "vs"]
    elif p.marker == "WEAPON":
        key, matkey, nm, col = "weapon", "weapon", f"Weapon {p.weapon}", COLOURS["weapon"]
    elif p.marker == "POST":
        key, matkey, nm, col = "post", "post", f"Post {p.post}", COLOURS["post"]
    else:
        return
    asset = None
    if bpy.context.scene.lp2_models and p.marker != "SPAWN":
        asset = asset_mesh({"VS": f"vs_{int(p.vs_type, 16):02x}" if p.marker == "VS" else "",
                            "WEAPON": f"wp_{int(p.weapon, 16):02x}", "POST": f"om_{POSTS_BY_ITEM[int(p.post, 16)][1][2:]}"}
                           .get(p.marker, ""), scale)
    if asset:
        ob.data = asset
    else:
        ob.data = marker_mesh(key, scale)
        ob.data.materials.clear()
        ob.data.materials.append(material(matkey, col))
    ob.color = col
    if not ob.name.startswith(nm):
        ob.name = nm


def on_change(self, context):
    refresh(self.id_data, context)


class LP2MarkerProps(bpy.types.PropertyGroup):
    marker: bpy.props.EnumProperty(items=[("NONE", "None", ""), ("SPAWN", "Spawn", ""), ("VS", "VS", ""),
                                          ("WEAPON", "Weapon", ""), ("POST", "Data post", "")], default="NONE")
    spawn_role: bpy.props.EnumProperty(name="Role", items=[(k, v[0], f"rInitPosSet kind {v[1]}") for k, v in SPAWN_ROLES.items()],
                                       update=on_change)
    vs_type: bpy.props.EnumProperty(name="VS type", items=VS_ITEMS, default="0x66", update=on_change)
    weapon: bpy.props.EnumProperty(name="Weapon", items=PICKUP_ITEMS, default="0x15", update=on_change)
    post: bpy.props.EnumProperty(name="Post", items=POST_ITEMS, update=on_change)
    tier: bpy.props.EnumProperty(name="Tier", items=TIERS)
    modes: bpy.props.EnumProperty(name="Game types", items=MODE_ITEMS, options={"ENUM_FLAG"}, default=ALL_MODES)
    slot1_on: bpy.props.BoolProperty(name="Mount 1", default=True)
    slot2_on: bpy.props.BoolProperty(name="Mount 2", default=True)
    slot3_on: bpy.props.BoolProperty(name="Mount 3", default=False)
    slot4_on: bpy.props.BoolProperty(name="Mount 4", default=False)
    slot1: bpy.props.EnumProperty(name="Weapon 1", items=VS_WEAPON_ITEMS)
    slot2: bpy.props.EnumProperty(name="Weapon 2", items=VS_WEAPON_ITEMS)
    slot3: bpy.props.EnumProperty(name="Weapon 3", items=VS_WEAPON_ITEMS)
    slot4: bpy.props.EnumProperty(name="Weapon 4", items=VS_WEAPON_ITEMS)


# ---------------------------------------------------------------- collections

def variant_collection(scene, variant):
    root = bpy.data.collections.get("LP2 Layout")
    if not root:
        root = bpy.data.collections.new("LP2 Layout")
        scene.collection.children.link(root)
    name = f"LP2 Variant {variant}"
    coll = bpy.data.collections.get(name)
    if not coll:
        coll = bpy.data.collections.new(name)
        root.children.link(coll)
    return coll


def markers(variant=None):
    out = []
    for v in range(4) if variant is None else [variant]:
        coll = bpy.data.collections.get(f"LP2 Variant {v}")
        if coll:
            out += [(v, ob) for ob in coll.all_objects if ob.lp2.marker != "NONE"]
    return out


def new_marker(context, kind, **settings):
    scene = context.scene
    ob = bpy.data.objects.new("LP2 marker", marker_mesh("spawn", scene.lp2_scale))
    variant_collection(scene, int(scene.lp2_variant)).objects.link(ob)
    ob.location = scene.cursor.location
    ob.rotation_euler = (0, 0, scene.cursor.rotation_euler.z)
    ob.lp2.marker = kind
    for k, v in settings.items():
        setattr(ob.lp2, k, v)
    refresh(ob)
    for o in context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    return ob


class LP2_OT_add(bpy.types.Operator):
    """Add a marker at the 3D cursor (facing the cursor's Z rotation)"""
    bl_idname = "lp2.add_marker"
    bl_label = "Add LP2 marker"
    bl_options = {"REGISTER", "UNDO"}
    kind: bpy.props.StringProperty()
    role: bpy.props.StringProperty()

    def execute(self, context):
        if self.kind == "SPAWN":
            new_marker(context, "SPAWN", spawn_role=self.role or "start")
        elif self.kind == "VS":
            new_marker(context, "VS")
        else:
            new_marker(context, self.kind)
        return {"FINISHED"}


class LP2_OT_ground(bpy.types.Operator):
    """Drop the selected markers onto the map geometry below them"""
    bl_idname = "lp2.drop_to_ground"
    bl_label = "Drop to ground"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        dg = context.evaluated_depsgraph_get()
        moved = 0
        for ob in context.selected_objects:
            if ob.lp2.marker == "NONE":
                continue
            origin = ob.location + Vector((0, 0, 50 * context.scene.lp2_scale))
            for _ in range(32):
                hit, loc, _n, _i, hob, _m = context.scene.ray_cast(dg, origin, Vector((0, 0, -1)))
                if not hit:
                    break
                if hob.lp2.marker == "NONE" and hob != ob:
                    ob.location = loc
                    moved += 1
                    break
                origin = loc + Vector((0, 0, -0.001))
        self.report({"INFO"}, f"{moved} marker(s) dropped")
        return {"FINISHED"}


def world(ob):
    """ob's world matrix from its parent chain: Blender leaves matrix_world stale (identity) for objects in
    hidden or excluded collections, which other variants' markers and LP1 sets usually are."""
    m = ob.matrix_basis
    while ob.parent:
        m = ob.parent.matrix_basis @ ob.matrix_parent_inverse @ m
        ob = ob.parent
    return m


class LP2_OT_from_lp1(bpy.types.Operator):
    """Make LP2 markers from the 'LP1 layout' empties (blender_lp1points.py): LP1 set 0N -> variant N"""
    bl_idname = "lp2.from_lp1"
    bl_label = "Markers from LP1 layout"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = bpy.data.collections.get("LP1 layout")
        if not root:
            self.report({"ERROR"}, "no 'LP1 layout' collection (blender_lp1points.py adds it)")
            return {"CANCELLED"}
        made = 0
        for coll in root.children:
            ids = coll.name.split()[1].split("/") if " " in coll.name else []
            for variant in range(4):
                if f"0{variant}" not in ids:
                    continue
                for e in coll.all_objects:
                    role, model = e.get("lp1_role"), e.get("lp1_model", "")
                    settings = {}
                    if role in SPAWN_ROLES:
                        kind, settings = "SPAWN", {"spawn_role": role}
                    elif role == "vs" and int(model[2:], 16) in VS_BY_ID:
                        kind, settings = "VS", {"vs_type": hexid(int(model[2:], 16))}
                    elif role == "weapon":
                        kind = "WEAPON"
                    elif model.startswith("om71"):
                        kind = "POST"
                    else:
                        continue
                    old = context.scene.lp2_variant
                    context.scene.lp2_variant = str(variant)
                    ob = new_marker(context, kind, **settings)
                    context.scene.lp2_variant = old
                    ob.location = world(e).translation
                    ob.rotation_euler = (0, 0, world(e).to_euler().z)
                    made += 1
        self.report({"INFO"}, f"{made} markers made (weapons default to slot 0x15: LP1 weapon ids differ)")
        return {"FINISHED"}


class LP2_OT_export(bpy.types.Operator):
    """Write the layout JSON for lp2layout.py"""
    bl_idname = "lp2.export_layout"
    bl_label = "Export Layout"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = bpy.path.ensure_ext(bpy.path.abspath("//") + "layout", ".json") if bpy.data.filepath else "layout.json"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        data = export_layout(context.scene)
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=1)
        n = sum(len(s["points"]) + len(s["objects"]) for s in data["sets"])
        self.report({"INFO"}, f"{n} markers in {len(data['sets'])} variant(s) -> {self.filepath}")
        return {"FINISHED"}


def export_layout(scene):
    s = 1.0 / scene.lp2_scale
    sets = []
    for v in range(4):
        pts, objs = [], []
        for _, ob in markers(v):
            p = ob.lp2
            w = world(ob).translation
            pos = [round(w.x * s, 2), round(w.z * s, 2), round(-w.y * s, 2)]
            yaw = round(math.degrees(world(ob).to_euler().z) % 360, 2)
            modes = sorted(p.modes)
            if not modes:
                continue
            if p.marker == "SPAWN":
                pts.append(dict(role=p.spawn_role, kind=SPAWN_ROLES[p.spawn_role][1], modes=modes, pos=pos, yaw=yaw))
                continue
            extra = dict(modes=modes)
            if p.marker in ("VS", "WEAPON"):
                extra["tier"] = int(p.tier)
            if p.marker == "VS":
                slots = [[int(getattr(p, f"slot{i}_on")), int(getattr(p, f"slot{i}"), 16)] for i in range(1, 5)]
                objs.append(dict(role="vs", model=f"vs{int(p.vs_type, 16):02x}", item=int(p.vs_type, 16), weapons=slots, pos=pos, yaw=yaw, **extra))
            elif p.marker == "WEAPON":
                objs.append(dict(role="weapon", model=f"wp{int(p.weapon, 16):02x}", item=int(p.weapon, 16), pos=pos, yaw=yaw, **extra))
            elif p.marker == "POST":
                item = int(p.post, 16)
                objs.append(dict(role="post", model=f"om{item & 0xff:02x}{item >> 8:02x}", item=item, pos=pos, yaw=yaw, **extra))
        if pts or objs:
            sets.append(dict(ids=[f"0{v}"], points=pts, objects=objs))
    return dict(source=bpy.path.basename(bpy.data.filepath) or "untitled", units="cm, LP2 stage space (Y up)", lp2=True, sets=sets)


class LP2_PT_panel(bpy.types.Panel):
    bl_label = "LP2 Map"
    bl_idname = "LP2_PT_map"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "LP2 Map"

    def draw(self, context):
        sc, lay = context.scene, self.layout
        row = lay.row(align=True)
        row.prop(sc, "lp2_variant", text="Variant")
        row.prop(sc, "lp2_scale", text="Scale")
        r = lay.row()
        r.prop(sc, "lp2_models", text="Game models" + ("" if asset_library() else " (no library)"))
        r.operator("lp2.refresh_markers", text="", icon="FILE_REFRESH")
        box_ = lay.box()
        box_.label(text="Add at 3D cursor")
        for row_roles in (("start", "team_a", "team_b"), ("k30", "k31", "k40")):
            r = box_.row(align=True)
            for role in row_roles:
                op = r.operator("lp2.add_marker", text=SPAWN_ROLES[role][0])
                op.kind, op.role = "SPAWN", role
        r = box_.row(align=True)
        r.operator("lp2.add_marker", text="VS").kind = "VS"
        r.operator("lp2.add_marker", text="Weapon").kind = "WEAPON"
        r.operator("lp2.add_marker", text="Data post").kind = "POST"
        ob = context.active_object
        if ob and ob.lp2.marker != "NONE":
            b = lay.box()
            p = ob.lp2
            b.label(text=ob.name)
            if p.marker == "SPAWN":
                b.prop(p, "spawn_role")
            elif p.marker == "VS":
                b.prop(p, "vs_type")
                vid = int(p.vs_type, 16)
                sx, sy, sz = VS_BY_ID[vid][2]
                b.label(text=f"{VS_BY_ID[vid][1]}: {sx} x {sy} x {sz} m" + ("  (flies)" if VS_BY_ID[vid][3] else ""))
                b.label(text="Weapon mounts")
                for i in range(1, 5):
                    r = b.row(align=True)
                    r.prop(p, f"slot{i}_on", text=f"{i}")
                    sub = r.row()
                    sub.enabled = getattr(p, f"slot{i}_on")
                    sub.prop(p, f"slot{i}", text="")
            elif p.marker == "WEAPON":
                b.prop(p, "weapon")
            elif p.marker == "POST":
                b.prop(p, "post")
            if p.marker in ("VS", "WEAPON"):
                b.prop(p, "tier")
            b.label(text="Game types")
            b.prop(p, "modes")
            if len(context.selected_objects) > 1:
                b.operator("lp2.copy_settings", text=f"Copy to {len(context.selected_objects) - 1} selected")
        lay.operator("lp2.drop_to_ground")
        counts = {}
        for _, o in markers(int(sc.lp2_variant)):
            k = SPAWN_ROLES[o.lp2.spawn_role][0] if o.lp2.marker == "SPAWN" else o.lp2.marker.title()
            counts[k] = counts.get(k, 0) + 1
        col = lay.column(align=True)
        col.label(text=f"Variant {sc.lp2_variant}: " + (", ".join(f"{k} {n}" for k, n in counts.items()) or "empty"))
        for role in ("start", "team_a", "team_b"):
            n = counts.get(SPAWN_ROLES[role][0], 0)
            if 0 < n < 16:
                col.label(text=f"{SPAWN_ROLES[role][0]}: {n} of 16 (points get reused)", icon="ERROR")
        lay.operator("lp2.from_lp1")
        lay.operator("lp2.export_layout")


class LP2_OT_copy(bpy.types.Operator):
    """Copy the active marker's settings (type, tier, game types, mounts) to the selected markers of the same kind"""
    bl_idname = "lp2.copy_settings"
    bl_label = "Copy marker settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        src = context.active_object.lp2
        names = [k for k in LP2MarkerProps.__annotations__ if k != "marker"]
        n = 0
        for ob in context.selected_objects:
            if ob != context.active_object and ob.lp2.marker == src.marker:
                for k in names:
                    setattr(ob.lp2, k, getattr(src, k))
                refresh(ob)
                n += 1
        self.report({"INFO"}, f"{n} marker(s) updated")
        return {"FINISHED"}


class LP2_OT_refresh(bpy.types.Operator):
    """Rebuild every marker's shape (after switching game models on or off, or changing the scale)"""
    bl_idname = "lp2.refresh_markers"
    bl_label = "Refresh markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obs = [o for _, o in markers()]
        for o in obs:
            refresh(o)
        self.report({"INFO"}, f"{len(obs)} marker(s) refreshed")
        return {"FINISHED"}


class LP2Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    library: bpy.props.StringProperty(name="Marker models", subtype="FILE_PATH",
                                      description="lp2_marker_assets.blend (game models for VS, weapons and posts)")

    def draw(self, context):
        self.layout.prop(self, "library")


CLASSES = (LP2Prefs, LP2_OT_refresh, LP2MarkerProps, LP2_OT_copy, LP2_OT_add, LP2_OT_ground, LP2_OT_from_lp1, LP2_OT_export, LP2_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.lp2 = bpy.props.PointerProperty(type=LP2MarkerProps)
    bpy.types.Scene.lp2_variant = bpy.props.EnumProperty(name="Variant", items=[(str(i), str(i), f"layout -0{i}") for i in range(4)])
    bpy.types.Scene.lp2_models = bpy.props.BoolProperty(name="Game models", default=True,
                                                        description="Show VS, weapons and posts as their game models (needs lp2_marker_assets.blend)")
    bpy.types.Scene.lp2_scale = bpy.props.FloatProperty(name="Scale", default=0.01, min=0.0001, description="Blender units per LP2 centimetre")


def unregister():
    del bpy.types.Scene.lp2_scale
    del bpy.types.Scene.lp2_models
    del bpy.types.Scene.lp2_variant
    del bpy.types.Object.lp2
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
