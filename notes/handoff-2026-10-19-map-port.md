# LP1 -> LP2 map port (2026-10-19)
(Map-port topic only. Everything else, incl. parts/chains/DLL state: handoff-2026-10-18c.md.)

## Battlegrounds test 1 (installed Maps/Battlegrounds.zip, awaiting test)
- lp2stage.py: LP1 stage models -> one LP2 static stage rModel (fmt 49b4f022) + rTextures (lp2tex),
  materials cloned from the template's first material (online00: BM/NM/MM + shared CM-01), LP1 _LM sampled
  into vertex colour (--light 0.5: x1 was ~2x Desecration's mean 52), flat NM / black MM stand-ins,
  --empty NAME = 1-triangle stand-in (online00_car1-4, online00_shadow are still drawn by the Scr scheduler).
  Winding checked (face normal agrees with vertex normal); reads back through mod2obj.
- Package = TestArena.zip with aArea_ONLINE_00_scr.arc rebuilt (stock entry order, 79 stage textures dropped,
  CM-01 kept), map.json name Battlegrounds, size large. Build dir: scratchpad bg/ (arc/, ta/).
- Test 1 keeps DESECRATION collision, spawns, objects (invisible floors): it only checks rendering.
- Next: collision writer (LP2 'SBC\xff' + BVHC from LP1 'SBC1' or the render mesh), spawns (patch rInitPosSet
  in place from points/s900.json), objects (rObjSet = same family as LP1 FSO), sky, alpha-tested materials.

## Requested features (user, 2026-10-19)
- Kill boxes / kill floors: candidates = SBC surface type flags only some maps use (0xe0000000, 0x44000000 on
  ONLINE_06/07/09) and tool\scrCollisionArea (.swc, only maps 04/08/11 have folders). Unverified.
- Animated elements (windmill, crushers, moving platforms) carrying kill boxes: LP2 stage props are separate
  rModels listed by the Scr rScheduler (online00_car1-4); motion/collision for movers not found yet. LP1 used
  SDL 'Move' tracks (s905 lights). Needs RE of an LP2 map with movers.
- Start (intro) camera: event_LP2\rt_online\onlineNN_cam.rScheduler per map (already noted 2026-10-16).

## Test results 2026-10-19 (evening)
- Battlegrounds test 1 loaded a STOCK-looking map: its _scr arc WAS served (log: aarea_online_13_scr.arc from
  ModCache) but resource paths = Desecration's (scr\Online\online00\online00; Test Arena uses the same) ->
  path-keyed resource cache likely reused the stock files. Fix (installed, untested): arcsub.py renames
  'scr\online\online00\' -> 'scr\Online\lp1bg900\' (same length) in names+data of _scr, base and _v arcs
  (also hit effect\efm_SCR\online\online00\ water entries, consistently). All 153 renamed refs resolve.
- Cloth still static after joint ids <= 127. Cause now suspected = bone count (legs 32, Basil body 39; every
  stock chained part <= 31). Re-ported: Snow Bunny --skirt 5,10:6 (26 bones), Basil --chains 56,64,70 (31).
  Installed, untested.
- Flying VS ignored ascend/descend: Controls plugin fly context only for fly_types [168 (0xa8), 218 (0xda)];
  -> LOGGED: user's flying VS ride id 0x02780000 = type 0x78 (120); added to fly_types (needs restart).
  user's VS probably another type. controls.json "log": true now -> next flight logs ride id (byte 2 = type).
  Descend bit (w2 0x40000) still a one-test guess.
- Map selection: System Link > Create Match with Battlegrounds -> first match (20:25) loaded map 00
  (aarea_online_00 requested), a later one (20:29) loaded slot 13. Selection of slot 13 gets lost sometimes
  (cf. "Saved Match forgets slot 13"). Unresolved; user to say whether 20:29 showed Battlegrounds visuals.
- Mods/test_map (old Desecration spawn-raise test) to be archived to lp2-assets/old-mods when the game closes
  (user OK'd removal).

## 2026-10-19 later: chain collision, faction option
- rChainCol decoded: 16 B header ('CCL\0', 0x0618, 8, count, size) + 64 B capsules (u32 1, u16 joint a, i16 joint b,
  u32 1, f32 0, vec3 offset on a @0x10, vec3 offset on b @0x20, radius @0x2C). Writer `rchain.build_col` (matches bd2500).
  Joints: 1 pelvis, 2/3 L thigh/knee, 5/6 R, 8 spine, 9 chest.
- lpc.json part key "chaincol" (DLL, kGenVersion 14). Basil body: torso 9->8 r25 + thighs r13; Snow Bunny legs: thighs
  r13 + 8->1 r20. Written by hand into export/ and Parts/; the exporter does not emit it yet (re-export drops it).
- `"mods": {"parts_any_faction": true}` sets the part menu's own ignore-faction byte (m+0x72f): stock + custom.
- `parts_first_slot` removed (dead since the carrier: fixed slots 20-39 + 69).
- Maps/TestArena.zip moved to lp2-assets/old-mods/. VS 0xc2 = stationary gun (no context yet).
