#!/usr/bin/env python3
"""LP1 layout -> explicit LP2 layout: what the export used to borrow from the stock map (Desecration) or guess,
written into the project's layout.json so the editor shows what the game gets.

  lp2convert.py --game LP2_DIR PROJECT_DIR      (lp2project.py import-lp1 --game runs it after the import)

Per marker set:
  - VS pairs: LP1 lists a layout's VS twice, at near-identical spots (lp1points.py "lp1_pair" 0 / 1); only the
    pair-0 VS stay (a set with only pair-1 VS keeps those)
  - VS tiers (rObjSet +0x04, the lobby's VS setting: None none, Few tier 0, Many 0 + 10, All every tier):
    TIERS by LP1 VS, else 0
  - vs56 (LP1's online bike; uVs56 doesn't work as a ride in LP2) -> the flying gear pickup, weapon 0x1f
  - LP1 weapons -> an explicit LP2 pickup: LP1_WEAPONS by LP1 id (the slot of the matching loadout category, or
    the grenade slot), a carryable VS weapon (VS_PICKUPS) keeps its id, anything else becomes Slot: Standard
  - the pickups the export put on the k40 points, then the FFA starts (the stock Team file's weapon records left
    over after the LP1 weapons, with their items and tiers) -> weapon markers at those points
and "explicit": true on the layout and every set (lp2layout.py then adds no stock pickups to the points). Markers that already have an
"item" / "tier" keep it. Running it twice changes nothing.
"""
import argparse, json, os, struct, sys, zlib

import arcx, objset

TIERS = {"vs50": 0, "vs51": 0, "vs53": 10}
# LP1 weapon ids (LostPlanetDX9.exe's id-ordered weapon name table: Hm-Anchor, Machine-Gun, Rifle, Energy-Gun,
# Anti-VS-Gun, ShotGun, Plasma-Gun, then H-Grenade = uWp08, every grenade type) -> the LP2 slot of the same loadout group
# (DX9 FUN_008a1980: 0x30 Standard = Machine Gun / Gun Sword / Energy Gun, 0x31 Short Range = Shotgun / Revolver /
# Flamethrower, 0x32 Long Range = Rifle / Plasma Gun, 0x33 Heavy Weapons = Rocket Launcher / Hand Cannon / Plasma
# Cannon, 0x34 Support; grenade slots 0x15 Normal, 0x16 Gum, 0x17 Disc, 0x18 Release, 0x19 Plasma). LP1 VS weapons
# (0x40 up) are LP2's under the same ids (same models; LP1's VS table: VS-Anchor, Vulcan, Laser-Rifle, Missile, ...)
LP1_WEAPONS = {0x01: 0x30, 0x02: 0x32, 0x03: 0x30, 0x04: 0x33, 0x05: 0x31, 0x06: 0x32, 0x08: 0x15}
# the VS weapons a soldier can pick up and carry: the ones the game names (DX9 FUN_008a1980); the rest are VS-only
VS_PICKUPS = {0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x60, 0x61, 0x62, 0x63}
STANDARD = 0x30
BIKE = 0x1F


def stock_weapons(game):
    """variant digit -> [(item, tier)] of Desecration's Team file group 4 (weapon) records, in order."""
    d = open(os.path.join(game, "nativePC", "arcXmlTmpPC", "aArea_ONLINE_00.arc"), "rb").read()
    types, out = arcx.load_types(), {}
    for n, th, cs, ds, fl, o in arcx.entries(d):
        if types.get(th) != "rObjSet" or "-team-" not in n.lower():
            continue
        b = d[o:o + cs] if cs == ds else zlib.decompress(d[o:o + cs])
        counts, _recs, _end = objset.parse(b)
        off = 0x30 + sum(counts[g] * objset.SIZES[g] for g in (1, 2, 3))
        recs = [b[off + i * objset.SIZES[4]:off + (i + 1) * objset.SIZES[4]] for i in range(counts[4])]
        out[n[-1]] = [(struct.unpack_from("<H", r, 0x1A)[0], struct.unpack_from("<I", r, 0x04)[0]) for r in recs]
    return out


def lp1_item(model, game):
    wid = int(model[2:], 16)
    if wid in LP1_WEAPONS:
        return LP1_WEAPONS[wid]
    if wid in VS_PICKUPS:
        return wid
    return STANDARD


def convert(lay, game):
    if lay.get("explicit"):
        return {}
    stock = stock_weapons(game)
    n = dict(pairs=0, tiers=0, bikes=0, weapons=0, pickups=0)
    for s in lay["sets"]:
        objs = s["objects"]
        pairs = {o.get("lp1_pair") for o in objs if o.get("role") == "vs"}
        if 0 in pairs and 1 in pairs:
            n["pairs"] += sum(o.get("lp1_pair") == 1 for o in objs)
            objs = [o for o in objs if o.get("lp1_pair") != 1]
        out = []
        for o in objs:
            o.pop("lp1_pair", None)
            if o.get("role") == "vs" and o.get("model") == "vs56":
                out.append(dict(kind=4, role="weapon", model="wp%02x" % BIKE, item=BIKE, tier=0, pos=o["pos"], yaw=o["yaw"],
                                **{k: o[k] for k in ("modes",) if k in o}))
                n["bikes"] += 1
                continue
            if o.get("role") == "vs" and "tier" not in o:
                o["tier"] = TIERS.get(o.get("model"), 0)
                n["tiers"] += 1
            if o.get("role") == "weapon" and "item" not in o:
                o["item"] = lp1_item(o["model"], game)
                o.setdefault("tier", 0)   # else the stock record's (the weapon setting filters like the VS one)
                n["weapons"] += 1
            out.append(o)
        # what lp2layout.patch_objset gave the points: stock record i -> (LP1 weapons + k40 + starts)[i]
        lp1_weapons = sum(o.get("role") == "weapon" for o in s["objects"])
        recs = stock.get(str(s["ids"][0])[1:2] if s.get("ids") else "0", stock.get("0", []))[lp1_weapons:]
        points = [p for p in s["points"] if p["role"] == "k40"] + [p for p in s["points"] if p["role"] == "start"]
        for p, (item, tier) in zip(points, recs):
            out.append(dict(kind=4, role="weapon", model="wp%02x" % item, item=item, tier=tier, pos=p["pos"],
                            yaw=p.get("yaw", 0.0), **{k: p[k] for k in ("modes",) if k in p}))
            n["pickups"] += 1
        s["objects"] = out
        s["explicit"] = True   # lp2layout.patch_objset reads it per set
    lay["explicit"] = True
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("project")
    a = ap.parse_args()
    p = json.load(open(os.path.join(a.project, "project.json")))
    path = os.path.join(a.project, p["layout"]["file"])
    lay = json.load(open(path))
    n = convert(lay, a.game)
    if not n:
        print("already explicit: nothing to do")
        return
    json.dump(lay, open(path, "w"), indent=1)
    print("%(pairs)d paired VS dropped, %(tiers)d VS tiers set, %(bikes)d vs56 -> flying gear, %(weapons)d LP1 weapons "
          "mapped, %(pickups)d point pickups made visible" % n)


if __name__ == "__main__":
    sys.exit(main())
