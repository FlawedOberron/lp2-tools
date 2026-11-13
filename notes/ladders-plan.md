# Ladders (bots + editor), found 2026-11-13

- Stock ladders are rObjSet group 3 ("post"/gimmick) records, kind 6, item 0x2283, at the ladder's foot:
  pos (+0x40), rot Y (+0x50, the facing), mUserData[4] (+0x84) = height in cm, [5] [6] = 50, 50 (half widths?).
  Collision under them is plain (no ladder material). The visible ladder is stage geometry.
  Unique ladders per online map: 01: 37, 02: 23, 06: 9, 09: 4, 04: 0, 08: 0 (others not counted yet).
- Capcom's training navmeshes (maps 01/09: aArea_TUTOREAL_41/46) mark them as vertical 2-triangle quads, ~80 cm
  wide, poly flag 0x8000, linked to the floor polys at the bottom and the top (link cost ~ the distance). Stock bots
  climb them there (user: Turbulent Junction).
- Our generated navmeshes (lp2navgen, stocknav for 02-08, 11, 15, custom maps) have none: map 06 bots "lost"
  (2228 of 6298 polys reachable, 100 no-path stalls in the 2026-11-13 match).
Plan:
1. lp2navgen / lp2stocknav: read the 0x2283 records, add the 0x8000 quad (foot -> foot + height, facing rot Y)
   joined to the nearest floor polys at both ends; lp2navmap: a ladder zone link (new kind), reachability through it.
2. bots.cpp: ladder link kind in ZoneWaypoint (cost ~ height x2), walked like a walk link (the game's own path
   follower climbs a 0x8000 poly - check), stall/blocked handling.
3. Editor: a Ladder object (foot point, facing, height) -> the 0x2283 record + nav quad; the visible ladder stays
   the map's geometry (or a stock ladder model if one exists: find the model the 0x2283 class loads, if any).
4. Rebuild stock navmeshes, check map 06 / 02 reachability.

## Done 2026-11-13 (stock side, untested in game)
- project.json "ladders" [{pos, yaw, height}]: lp2project import-lp2 fills it from the om8322 records
  (lp2layout.stock_ladders); lp2mapc NAV_INPUTS hashes it.
- lp2navmap.add_ladders: an 80 cm vertical quad (2 tris) per ladder, welded to the floor at the foot and at the top
  (looked for 0/40/80/120 cm out, either side; floor within 80 cm of the foot / 150 cm of the top). Ladder polys:
  no zone, no jump/grapple open edges; zone links "ladder" both ways. lp2navgen.write flags them 0x8000.
  Hand-edited OBJs drop vertical triangles on read (ladders are added again each build).
- DLL: kNavLadder (5): walked (the game's pathing climbs), cost 200 + 1.5 x height, no unstick.
- Stock builds use auto welds 60 cm (STOCK_WELD): map 06 main piece 944 -> 2019 of 2246 polygons.
- Map 06: all 9 ladders placed. Dropped area is scenery (sea plane y -8000, hills 40-85 m). 12 markers off the
  navmesh: (-1444,3950,-900), five at ~(-130,2200,-6650), (172,1160,-11299), three at ~(200..500,2260,-11300),
  (405,1610,-4930), (6206,3000,-3297): high spots (launcher landing?). Launcher: not found yet; candidates in
  -Common: om8349 (x3, userdata 30/110, 32/135, 18/190 ...; two relative points +0xbd0/+0xbe0), om8347 (x2, pitch 60),
  om8256 (x3, ~900 cm from each om8349). User offered to point it out in the editor.
- Fix (same day): ladders cut map 08's playable area 5070 -> 4690. Cause: regions() joined the ladder welds before the
  jump / grapple pass, so merged regions shared one GRAPPLE_TRIES (40) budget per pair and lost grapple joins. Now
  regions(late=ladder welds) joins them after: map 08 5098 (as with unlimited tries). seed_polys also skips vertical
  / sliver triangles (|2D area| <= 1) for the marker hit and the centroid fallback.
Next: editor Ladder tool (place foot / facing / height; export writes om8322 records into the Common objset from a
stock template), launcher -> launch link for stock maps.

## Stock navmesh check, 2026-11-13 evening (rebuild with the ladder fix; installed, untested in game)
Ladder links per map: 00 20, 01 32, 02 40, 03 24, 04 22, 05 6, 06 18, 07 22, 08 28, 09 6, 11 20 (10, 12, 15 none).
Playable polys: 07 9410 (was 9318 with the bug), 08 5098 (was 5070 before ladders).
Markers (spawns + AI points) with no kept navmesh under them, clustered 15 m, centre in metres (x, y, z), largest
first. Not all are floor spots (some AI points float), so these are places to look at in the editor, not proven gaps:
- 07: 144 of 829. 15@(-357,28,-115) 15@(-357,28,121) 10@(-291,-23,-24) 10@(-438,58,-65) 10@(-438,58,72)
  10@(-443,58,-117) 8@(-356,44,151) 7@(-347,46,173). Also dropped (unseeded) floor: 5722 m2 @(-144,77,64),
  2435 m2 @(-116,55,-158), 1173 m2 @(-129,58,154). Main piece only 55%. Most likely a real 06-style gap: the far -x end.
- 15: 255 of 879. 68@(84,-2,268) 38@(70,4,47) 28@(15,40,167) 15@(7,7,182) 11@(36,1,162) 10@(89,16,281).
- 01: 382 of 1140. 59@(54,15,45) 50@(24,7,-42) 32@(43,0,-90) 32@(-86,3,-100) 20@(6,3,-60).
- 03: 62 of 795, all at the z -290..-360 end: 14@(-20,19,-333) 12@(-119,13,-329) 12@(-67,15,-355). Main piece 52%.
- 04: 50 of 816, all around x -170..-245, z 375..480 (one corner). Main piece 47% (rooftops, grapple-linked).
- 05: 61 of 955. 17@(67,15,-4) 9@(97,15,-162).   11: 61 of 820. 15@(-126,2,85) 10@(-71,22,-131).
- 06: 19 of 789. 9@(-2,22,-67) 7@(4,21,-111): the two high spots at ~22 m (launcher landing?). Dropped floor at
  42-64 m: 1837 m2 @(-124,42,-2), 1119 m2 @(-70,44,-117), 722 m2 @(43,50,45) (hills or reachable?).
- Fine: 00 (18), 02 (2), 08 (4), 09 (8).
- 10, 12: Capcom's training navmesh (not generated).
Scripts: stock_mapreport.py WORK (pieces / dropped chunks), stock_offmarks.py WORK mapNN... (markers), both read
<work>/mapNN/.preview/navmesh.bin.
- User 2026-11-13: map limits for stock bots (lp2stocknav STOCK_LIMITS, limits volumes added at import):
  07 NEOS: floor centre (-21525,-3230,2788), size (19210,8510,28150). Low gravity + jump packs, so the map hangs
  together by jump-pack flights (the ships out wide too); bots stay in the box. 15 Frozen Wasteland: (-120,389,15855)
  size (26910,6870,33030): the central crater; y 389 taken as the box's middle (as the floor it cut half the
  crater floor; the editor's Position is the floor centre, user may have typed the middle). 06 launcher still open.
  lp2stocknav --reuse --rebuild 07,15 rebuilds just those maps.

## Spawns over no navmesh: causes (2026-11-13, user: "something wrong with our translation?")
- The earlier "markers off the navmesh" list counted every layout point and object. Spawns only, with the real floor
  under each (stock_spawncheck.py WORK [mapNN]): most maps fine.
- Translation bug: ONLINE_01's archive also holds ONLINE_00's 29 rInitPosSet files (aArea_Online_00-*), and
  stock_layout took every file, so Turbulent Jungle's layout had map 00's spawns (floating over nothing). Fixed:
  lp2project.own_file filters by the map number in the name (01: 1140 markers -> 759; navmesh unchanged). Editor
  imports of Turbulent Jungle made before this have the extra spawns: re-import.
- Navgen: the inside-solid test (lp2navgen.inside_solid, for ONLINE_12's hollow blocks) dropped floors under top-only
  ledge / overhang sheets: Frozen Wasteland 74 spawns on floor without navmesh. nav_settings "solid": false skips it;
  stock builds use it (15: 74 -> 20, playable 41351 -> 51421 polys, 872 of 879 markers seeded).
- Left: NEOS 99 spawns with no floor (x -360..-450 m, outside the box: ships?), 16 under the box floor (y -46 m);
  Cube's floor is the moving cubes (Capcom navmesh); small counts on 03 / 04 / 05 / 11.
- Full stock rebuild with solid off (installed, uncommitted): every map same or better on stock_spawncheck; playable
  polys 00 25355->25585, 02 5648->5968, 04 7025->7855, 05 20658->23241, 06 2246->2278, 07 8643->9049, 08 5098->5472,
  11 44901->47170, 15 41351->51421. stockarea.bin 5.78 -> 6.37 MB. Editor has no "solid" toggle yet (custom maps keep
  the test on unless project.json nav_settings.solid = false).
