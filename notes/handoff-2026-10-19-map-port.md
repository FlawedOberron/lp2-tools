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

## Battlegrounds test 2 (installed, untested)
- Test 1 result: geometry OK; collision/spawns/objects = map 00 (expected). Crash before that = stale part package
  (chaincol thigh joints missing from Basil body); fixed by the chain/col file stamp in parts.cpp + crash logger
  (mods/crashlog.cpp: vectored handler -> "crash:" lines, exe addresses at preferred base).
- lp2col.py: LP1 PC (Steam LP1 nativePC/ZZPack2/s900.arc, little-endian SBC1) ataris900/tamas900 -> LP2 SBC\xff
  with BVHC (format in its docstring; validated: every leaf once, boxes contain tris; stock passes the same check).
  LP1 surface flags 0x8000xxxx -> 0x4000xxxx match online00's table exactly. sbc.py doc fixed (no plane distance).
- lp2layout.py: patches stock rInitPosSet (Pos/Dir in place) and rObjSet (VS/weapon positions, extras dropped)
  from points/s900.json; variant -0N <- LP1 set '0N'. Weapons: LP1 lists 2 per layout, extras go on k40 points
  then FFA starts.
- arcput.py: replace arc entries by name suffix + class. rOccluder count zeroed (map 00 occluders would cull).
- Package build: scratchpad bg/v2 (from ta/) -> Battlegrounds2.zip -> Maps/Battlegrounds.zip (test 1 kept as
  bg/Battlegrounds-test1.zip). Still map 00: havonline00 (Havok physics), rAreaHitLayout, SceneBox/lighting,
  radar map, posts (objset groups 2/3), sky.

## Battlegrounds tests 3-4, Blender marker tool (2026-10-19 late)
- Test 2 result: movement collision, spawns, weapons good; grenades pass through (Havok havonline00 still map 00),
  no data posts (stock posts dropped with LP1 layout), one VS stuck in a room + a flying transport (map 00's VS
  types moved onto LP1 spots). -> notes/vs-ids.md: LP2 ships every LP1 VS id with the same model; test 3 used
  lp2layout --lp1-vs (LP1 types/counts).
- objset findings: VS record +0x120 = 4 weapon mounts x 5 B (u8 on, u8 4, u16 weapon id, u8 0), 0x41 default;
  +0x04 = tier 0/10/20 on VS + weapons in every mode (~45/33/22 %) = presumably the match's amount setting
  (None/Normal/Maximum); posts = group 3 kind 6 om71xx (om7100 bytes "71 00"; is_post = rec[0x19]==6 and
  rec[0x1A]==0x71). Weapon pickup ids with 0 KB uWpXX.arc are SLOTS (match settings pick the weapon):
  0x0c, 0x15-0x19, 0x30-0x34, 0x41, 0x43, 0x44; the rest are fixed weapons with models.
- Test 4 (installed): layout exported by the Blender tool from the LP1 import + a SLOT TEST ROW: 13 weapon slot
  pickups (0x0c, 0x15-0x19, 0x30-0x34, 0x43, 0x44, in that order) every 2.5 m from 3 m in front of (yaw
  direction, LP2 +Z assumed forward) the first Team A, FFA and Team B spawn of every variant. User to say what
  each one is (Standard/Short/Long/Heavy...) -> SLOT_NAMES in the add-on.
- blender_lp2_map_markers.py (add-on): sidebar "LP2 Map": add spawns (FFA/A/B/bases/extra), VS (type, 4 mounts),
  weapons (slots first), data posts at the cursor; tier + game types per marker; drop to ground; copy settings;
  markers from the LP1 import; Export Layout -> JSON ("lp2": true) for lp2layout.py, which now filters by game
  type (file name), rebuilds VS/post/weapon groups from markers (stock records cloned, any count; non-post
  group-3 gimmicks dropped) and writes tiers + mounts. Spawn counts still fixed by the stock rInitPosSet.
- Game-model markers: build_marker_assets.py (uVs/uWp/uOm archives -> OBJ+DDS, lp2-assets/markers, 142 models)
  + blender_marker_assets.py -> lp2_marker_assets.blend (top LOD, 512 px packed textures); the add-on appends
  "LP2 asset <key>" meshes from it (next to the add-on or set in its preferences).

## Battlegrounds 5-6 (2026-10-20)
- v5: lp2havok.py (LP1 Havok 4 havs900 -> LP2 6.6 rHkCollision, MOPP bytecode reused as-is) put into _v arc as
  havokdata\havonline00 (only arc holding it). Grenades tested OK in game (2026-10-20).
- Test 4 result: spawned under the map / posts outside. Cause: Blender keeps matrix_world as identity for objects
  in hidden/excluded collections; blender_lp1points shows only the first LP1 set, so from_lp1 put variants 01-03
  at the origin (export had the same bug). Fixed: world() in the add-on builds the matrix from the parent chain.
  The old layout also had add-on test markers (1000,500,-2000) and 3 drop_to_ground'd starts.
- Each map has several layouts (variants -00..-03 per game type; LP1 sets 0N, plus per-mode sets 1N-8N).
- v6: layout regenerated headless (scratchpad regen_layout.py: lp1points + from_lp1 + export, no test markers);
  floorcheck.py (vertical ray vs atari) passes every marker. Slot rows moved to a spawn/direction with floor.
  Posts: LP1 has one om7101 per match at 4 distinct sites across its sets; every variant now gets all 4
  (stock LP2 modes have ~5).
- blender_marker_assets.py failed: om_7103's MTL names om7100_BM-00.dds that was never copied -> skip missing
  textures (todo).
- Test 6 result: posts show (all 4 LP1 sites sit nearer Team A base k30 -> unbalanced); radar still map 00's
  (needs a builder); map 00's big windmill still in the background (sky/distant scenery, with lighting todo);
  slot row read "down the line": frag, gum, disk, decoy, plasma, then standard, short, long, heavy, special
  (AR, shotgun, sniper, RL, shield) = 10 names for 13 ids; pickups re-rolled shortly after Go (likely each slot
  -> a random weapon of its class). Mapping to ids pending (row direction to confirm).
- Pickups "shuffled to other locations" after Go: objset records carry their group index at +0x110 (u32);
  cloned extras repeated index 0. lp2layout now renumbers -> Battlegrounds7 installed (only change vs 6). Untested.
- Leftover watcher bof1po5x5 never exited: its pgrep -f pattern matched its own command line (use the
  'a''b' split trick in watchers too).
- v8 (installed): posts balanced (scratchpad mirror_posts.py): each LP1 post site gets a partner at a known-good
  LP1 spot (start/k40/VS/weapon pos) with swapped distances to the bases k30/k31, snapped to the nearest floor.
  8 posts per variant, ~4 per side. Point mirroring failed (map not point-symmetric).
- Sky/lighting findings: our ported online00 already carries LP1's own sky dome + distant terrain (mat000-004,
  +-130 km); stock Desecration's dome (mat009, r 322 km) is gone with its stage model; car1-4/shadow are stubs;
  o00water/o00water2 effect models = flat water planes at y -221 (Desecration coords). No windmill source found
  in map-00 data -> ask user for screenshot / whether it is LP1's.
  Lighting = Light0-3_windows rScheduler (HemiSphereLight, directional light, LightSpaceShadow, ambient),
  Filter0-3 (Bloom, ColorCorrect, DOF, ToneMap, Rayleigh/Mie scattering with mSunDir/mSunColor) and
  rSceneBox2 'SBL\0' v0x103: 44 boxes x ~2106 B (baked probes) inside bounds x/z +-14.4k (Desecration).
  Battlegrounds z reaches -21.5k -> outside the boxes.
- v9 (installed, untested): lp2light.py = static daylight + start camera. Sun towards (0.472, 0.848, 0.241)
  from a fit of LP1's baked vertex light vs normals (scratchpad sunfit.py; weak r2 0.07; baked light is cool:
  lit 88/98/108, away 64/72/79); sun colour tint 0.93/0.97/1.1; every day/night key = key 0; spot light off;
  SceneBox2 grid all zone 42 over x -2000..17600, z -23500..-500. Camera (online00_cam, 4 keys / 90 frames,
  mOffsetPos + mTrackTarget absolute) = arc ~7 km round (9000, 2370, -9500), keys 1.2 km over local terrain,
  line of sight checked (scratchpad light/cam.json). Shadow regions (32 capsule + 8 point) still Desecration's.
- Thumbnail: no per-map picker image found (ID230_MAP_ID = world map backdrop; lobby arcs only icons) -> ask
  user where it shows.
- Test 9 (user): slot row = 0x0c Handgun, 0x15-0x19 Frag/Gum/Disk/Dummy/Plasma grenade, 0x30-0x34 Standard/
  Short/Long/Heavy/Special; 0x41/0x43/0x44 = VS mount slots (no ground pickup) -> SLOT_NAMES in the add-on.
  Windmill = om835a in -Common.osf (map 00's gimmicks for every mode, + 11 x om8322) -> lp2layout drops the
  Common file's gimmicks for authored layouts. Yellow sky = Filter mpAreaLScattering mSunColor (10,9,4); green
  cast = ColorCorrectFilter mToneCurveR/G/B (kind 14, 4 f32) -> lp2light --sky / --bloom / --curves.
- Thumbnail: create-match circle = aBattlePlayerCreate.arc flash\dds\ID221_SC00_ID..SC13 (512 DXT5, 1 mip,
  circle r 200.5 in alpha). DLL (uncommitted, built): map zip may hold thumbnail.rTexture -> generated
  aBattlePlayerCreate.arc with ID221_SC<slot>_ID replaced (packages.cpp, cache "lp2-maps 2"). lp2thumb.py makes
  one from any picture (placeholder from the user's 12:37 screenshot).
- Battlegrounds10 built (scratchpad bg/Battlegrounds10.zip): layout11 = no slot-test rows, LP1 weapons + 30 slot
  pickups on k40 + FFA starts (stock-like gun/grenade/handgun mix, tiers 0/10/20), Common gimmicks dropped, sky/
  bloom/curve overrides, thumbnail. installed 2026-10-20 with the new xlive.dll (old one: xlive.dll.pre-thumb); copy kept in lp2-assets/maps/.

## 2026-10-20 Basil / Luka setup blends (lp2-assets/lp1/port, not exported yet)
- lp1port: LP1 colour maps with >25% see-through texels (CUTOUT) keep their alpha; their triangles get the
  template's alpha-tested twin material (word0 | 0x4000, word34 = 1 in the stock parts; UNVERIFIED in game).
  Basil: laces set (0,13) hm05-04 -> body mat 1, hair (1,1) -> head mat 4. Luka: head mat 4, body mat 1.
- lp1port --trim-legs 1: leg triangles above the template body floor go to the body only (Basil's poked above
  her belt). Basil re-ported with it (+ --head hmcc --body-groups 6,17 --chains 56,64,70).
- Basil B (black) / C (brown) colour maps: scratchpad basil_schemes.py recolours low-saturation outfit texels on
  body + legs; images lp1basil_{body,legs}_{B,C} sit unlinked in the materials (exporter picks them up by name).
  Fur collar speckled -> user to touch up. Backups: basil.pre-alpha.blend.
- FIXED: flat NM / black MM in exports = Blender GENERATED images regenerate on reload / colour-space change.
  lp1port now saves each atlas as PNG then switches the image to FILE source + reload + pack. Old blends fixed
  with scratchpad imgs_to_files.py (basil, luka). Basil legs: user split knife/belt/back; legsmix 1024^2 atlas
  (body below, legs above) + body->lg / bd->bk material renumbering by flags (fix_split.py).
- Template effects: 29xx parts carry rEffectProvider + act_hm29_and_lamp00 (lamp glow). xlive (uncommitted,
  installed, backup xlive.dll.pre-noeffects): lpc.json part "effects": "none" swaps the provider for the
  407-byte empty one (26 stock parts use it, e.g. bd2c00); kGenVersion 15. Exporter writes it by default
  (lp2_effects = "template" on part/set collection keeps them). docs/LP2-MODS.md updated.
- New set LPC_lp1basilcb "Basil (Agent)": LP1 hmcb (cutscene body, better model) + hmcc head, --trim-legs 1.
  blend lp1/port/basil_cb.blend. Installed, untested.
- Deleted LPC_lp1basilnp (poncho-free Basil from hm05) at user request: installed set, blend, export, textures. Replaced by LPC_lp1basilcb (hmcb).
- LPC_lp1basilcb colours B/C/D (scratchpad cb_schemes.py): grey gear (boots/belts) -> NEVEC FF (bd2904) cloth medians: B brown x2.2, C urban grey x1.6, D black; A original. Installed, untested.

## Area 921 (s921) test 1 (2026-10-21, built, installs when the game closes)
- s921 is Colonies-only: source = Xbox 360 ZZPack2/s921.arc (big-endian). lp2col / hkpack / lp2havok now read
  big-endian SBC1 and Havok 4 packfiles (layout rules byte 0x11 = little endian flag).
- Build (scratchpad a921/): lp2stage s921 + s921_sky (sky dome +-7.7 km, 1 mesh) -> packed _scr arc as for
  Battlegrounds; package = copy of Battlegrounds v10, paths online00/lp1bg900 -> 'scr\Online\lp1ar921\'
  (arcsub); atari 27k / tama 65k tris; havok 65k tris MOPP 677 KB; layout = regen_layout + markers lifted
  onto the floor (lift.py, <= 60 cm) + 30 slot pickups on k40/start (as layout11); 1 data post per variant
  (no mirroring yet); light = Battlegrounds' sun/sky/curves, bounds -13300..9650 x -15200..14600,
  intro camera = high orbit (y 7500, r 10 km) round (-1827, -850, -296). No thumbnail. Copy in lp2-assets/maps.
