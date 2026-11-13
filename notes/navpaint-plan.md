# Painted navmesh zones for stock maps (user idea 2026-11-13, not started)

User: painting zones on the navmesh (or areas as "inconsequential") beats boxes / volumes.

Have already:
- Editor Navmesh toolbar: Remove / Add as a click (whole piece) or brush drag; saved as world points
  (project.json "nav_removed" / "nav_added": {"brush": [[x,y,z]...], "r"} or {"piece": [x,y,z]}), so they survive
  rebuilds. lp2navmap.marked / removed apply them.
- Edit projects of stock maps carry source {"lp2": "NN"} (NEOS(edit) = 07, FrozenWasteland(edit) = 15).
- Gap: lp2stocknav re-imports each stock map from the game, so none of that paint reaches the stock bots. The
  stopgap is STOCK_LIMITS boxes (07, 15) in lp2stocknav.py.

Plan:
1. Stock paint file: lp2-tools/stocknav/mapNN.json = the stock map's nav keys from the editor (nav_removed,
   nav_added, nav_quiet, limits volumes, ladders added by hand later). lp2stocknav.build merges it into the fresh import.
   STOCK_LIMITS boxes move into these files (or go once painted).
2. Editor: in an edit project with source.lp2, a Navmesh toolbar button "Use for stock bots" writes that file (asks
   for the lp2-tools path once, in settings). Rebuild: lp2stocknav --reuse --rebuild NN.
3. New paint kind "Quiet" (inconsequential): brush like Remove, shown in its own tint; stays walkable and routable
   but bots never pick roam goals / hold points there (out-of-the-way ledges, the ships on NEOS). navzones: zone flag
   bit; stocknav format + bots.cpp RoamPoint / region picks skip flagged zones. Custom maps get it too (same key).
Order: 1+2 (no DLL change), then 3.
