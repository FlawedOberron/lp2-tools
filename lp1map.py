#!/usr/bin/env python3
"""Port a Lost Planet 1 multiplayer map to Lost Planet 2: one LP1 stage archive -> one Maps\\*.zip package.

  lp1map.py --game LP2_DIR --lp1 sNNN.arc --name "Area 921" OUT.zip [options]

Now a shortcut for lp2project.py import-lp1 + lp2mapc.py (the project is kept with --project DIR).

--lp1: the Xbox 360 (Colonies) ZZPack2/sNNN.arc; every stage model, collision, physics and layout comes
from it. The package is stock online map 00 (Desecration) with everything map-specific swapped:
  stage model + textures   lp2stage.py (LP1 lightmaps baked into vertex colour)
  collision                lp2col.py (atari = movement, tama = bullets)
  physics (grenades...)    lp2havok.py
  spawns, VS, weapons      lp1points.py + lp2layout.py --lp1-vs, or --layout (Blender LP2 Map Markers export)
  light, sky, intro camera lp2light.py (static daylight; --sun etc.; no weather or water; written to both
                           the main and variable arcs, whose copies the game uses); Desecration water planes stubbed
  occluders                emptied (map 00's would cull the new geometry)
  resource paths           arcsub.py 'scr\\Online\\online00\\' -> 'scr\\Online\\<tag>\\' so the game's
                           path-keyed cache never mixes it up with Desecration or another ported map
Every file comes from the user's own game install and LP1 archive; the zip is for personal use / sharing
between players who own both games, like any Maps package.

Options:
  --tag NAME      8-character resource folder (default lp1sNNN_); must differ between packages
  --size S        small / medium / large: the lobby's size class (default large)
  --layout JSON   authored layout (blender_lp2_map_markers.py "Export Layout") instead of LP1's own
  --sun X,Y,Z     direction towards the sun (default 0.472,0.848,0.241); --tint R,G,B the sun colour
  --sky / --bloom / --curves   lp2light.py filter overrides (defaults: Battlegrounds' neutral daylight)
  --thumb IMAGE   create-match thumbnail (lp2thumb.py; --zoom, --at)
  --exclude TEXT  skip LP1 stage models whose name contains TEXT (repeatable; e.g. _sky)
  --water CM      water plane at this height (default none)
  --project DIR   keep the imported project there (open / edit / recompile it later)
  --work DIR      keep the intermediate files there (default: a temporary folder)
"""

import argparse, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2mapc, lp2project  # noqa: E402

LIGHT = dict(sun="0.472,0.848,0.241", tint="0.93,0.97,1.1", sky="8.5,9.2,10", bloom="0.42,0.45,0.5",
             curves="R:0,0.215,0.69,0.97;G:0,0.222,0.70,0.985;B:0,0.227,0.711,1")


def floats(v):
    return [float(x) for x in v.split(",")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--lp1", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--tag")
    ap.add_argument("--size", default="large", choices=("small", "medium", "large"))
    ap.add_argument("--layout")
    for k, v in LIGHT.items():
        ap.add_argument("--" + k, default=v)
    ap.add_argument("--water", type=float)
    ap.add_argument("--thumb")
    ap.add_argument("--zoom", default="1")
    ap.add_argument("--at", default="0.5,0.5")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--project")
    ap.add_argument("--work")
    ap.add_argument("out")
    a = ap.parse_args()
    proj = a.project or tempfile.mkdtemp(prefix="lp1map-project")
    p = lp2project.import_lp1(a.lp1, proj, a.name, a.tag, a.size, a.layout, a.exclude)
    env = p["environment"]
    env.update(sun=floats(a.sun), tint=floats(a.tint), sky=floats(a.sky), bloom=floats(a.bloom), water=a.water,
               curves={c.split(":")[0]: floats(c.split(":")[1]) for c in a.curves.split(";")})
    if a.thumb:
        p["info"]["thumbnail"] = dict(image=os.path.abspath(a.thumb), zoom=float(a.zoom), at=floats(a.at))
    lp2project.save(proj, p)
    lp2mapc.compile_project(a.game, proj, a.out, a.work)


if __name__ == "__main__":
    main()
