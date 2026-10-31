# LP2 Map Editor (GUI) — plan (2026-10-22)

Goal: a standalone editor that opens stock LP2 maps, LP1 / Colonies maps and our own, edits them in a 3D
viewport and exports a Maps\*.zip package (the format the DLL already loads, shares and syncs).

## What we already have (the editor's back end)
| Need | Tool today | State |
|---|---|---|
| Stage model in / out | lp2model.py, lp2stage.py (LP1 -> LP2 static stage, baked vertex light) | works (Area 921, Battlegrounds) |
| Collision | lp2col.py (atari = movement, tama = bullets, BVH), lp2havok.py (physics) | works from LP1; no "author from mesh" yet |
| Spawns / VS / weapons / posts | objset.py, lp2layout.py, blender_lp2_map_markers.py (layout JSON) | works, per-variant (layout 00-03) |
| Lights / sky / filter / weather / water flag / intro camera | lp2light.py | works; green cast unsolved (parked) |
| Navmesh + waypoints | lp2nav.py (LNV v9 / WAY v16 read+write), blender_lp2nav.py | read/write/view; no generation |
| Thumbnail | lp2thumb.py | works |
| Packaging + slot | lp1map.py (pipeline), arcx / arcput / arcsub, mapslot.py | works, LP1-specific |
| Textures | tex2dds.py, lp2tex.py, lp1tex.py | works |
| In-game side | DLL: packages, slot 13/14, transfer, map.json | works (transfer slow) |

So the editor is mostly a GUI + project format over these, plus a general "compiler" replacing lp1map.py.

## Architecture
1. **Project file** (`MyMap.lp2map/`): `project.json` (map info, layouts, objects, prefabs, environment,
   volumes, paint layers, nav settings) + `assets/` (imported meshes / textures / collision).
   Text-based so it diffs and survives tool updates. The editor never edits arcs directly.
2. **Compiler** (`lp2mapc.py`, Python, headless): project -> Maps\*.zip. Generalises lp1map.py: stage build,
   collision + havok bake, ObjSet / InitPos per layout, schedulers (light / filter / efc, both arcs),
   water, nav, thumbnail, map.json. Same command the GUI's Export button runs; usable in CI / by hand.
3. **Asset cache** (`lp2cache.py`): reads the user's own LP2 (and LP1 / Colonies) install, converts what the
   editor shows to glTF + PNG under `~/.cache/lp2-editor/<game-hash>/`. Nothing from the games is shipped.
4. **GUI**: 3D viewport + outliner + inspector + toolbars, talks to 2-3 through files / subprocess.

### GUI stack: Godot 4 (user decided 2026-10-22)
- **Godot 4 (recommended)**: real app for players (Linux + Windows, one download), viewport, gizmos, UI kit,
  runtime glTF loading, MultiMesh / instancing, lightmap preview. Python tools run as subprocesses.
- **Blender add-on**: fastest to start (we already use Blender for markers / nav; linked duplicates = instancing
  for free, face attributes = painting, Eevee = lighting preview), but players need Blender and its UI.
- Qt + custom OpenGL: most work, no gain over Godot.
Possible path: Godot for the app; keep the Blender scripts as a power-user route on the same project format.

## Feature plan (user's list -> design)
1. **Game models for markers**: cache ? Man (built-in set) for spawns — red / blue team tint, green = generic;
   VS (vs*), weapons (wp*), pickups, data posts (om7100 family in LP2: find id), flags / CTF objects, intro
   camera (frustum gizmo + path keys, as lp2light --cam). Catalogue built from stock rObjSet / rInitPosSet
   classes (objset.py) so every placeable type a stock map uses is offered.
2. **Prefabs**: prefab = visual mesh + collision mesh (+ material: ground type) + textures. Placed copies are
   instances (transform + prefab ref) in the project; edits to the prefab update every copy.
   - Export: baked into the stage model + collision (always works).
   - Saving memory in game (point 10): research whether ObjSet objects (om class, own model + collision)
     can place one shared model many times — then repeated prefabs export as objects, not baked triangles.
3. **World objects**: lights (sun / ambient / hemisphere live in the Light scheduler; spot lights = PL_SpotLight
   tracks, count limited by the stock scheduler; more = baked), sound nodes (research: area ambience
   rSoundRequest / sequence placement), fog (efc mFogData + filter scattering), volumes (kill / damage /
   T-ENG refill / water: project data -> map.json, DLL tests players against them; host decides online),
   water level (efc mWaterExist / mWaterHeight) + water surface mesh/texture, sky (dome model + light; the
   green fix may be "use a stock map's sky + scheduler set").
4. **Painting**: per-face attributes on the stage / prefabs: ground type (collision material: SNOW, DEEP_SNOW,
   WATER, SAND, METAL... from the exe list), footstep / ricochet sound, "no gravel / no decals" style flags.
   Exported into rCollision face materials (+ havok material).
5. **Import existing maps**: stock LP2 online maps (stage, collision, layouts, schedulers) and LP1 / Colonies
   (lp1map pipeline pieces) -> a project, so custom versions start from the real thing.
6. **Layouts 1-4**: every placeable has a layout bit mask (1,2,3,4, any combination); a quick switcher
   (keys 1-4 / toolbar) shows one layout, others ghosted. Export writes the per-variant ObjSet / InitPos.
7. **Transform**: move / rotate / scale gizmos, snapping (grid, surface, angle), duplicate, align to ground
   (as lift.py did), multi-select, undo / redo.
8. **Navmesh**: show (lp2nav), edit (poly flags, links, cover waypoints), generate from walkable collision
   (Recast-style: voxelise -> regions -> polys -> LNV), "Has Navmesh" flag in map.json -> bot match list.
   Radar (user 2026-10-27): custom maps' blank radar is solved with the navmesh: render the radar map from
   the navmesh + height (or the navmesh split into floors, one radar layer per floor).
9. **Viewport + map info**: fly camera, lit preview (game sun / ambient / filter approximation, baked vertex
   light on / off), play-area bounds, radar map preview. Map info: name, thumbnail (capture from viewport),
   player count, size class, nav supported, modes supported.
10. **Dynamic objects**: tanks / cars / destructibles / crushers = stock object classes in ObjSet; the editor
   offers the ones the catalogue (1) finds, with their parameters. New behaviours are out of scope at first.
11. **Reuse game assets**: a package can point at stock resources by path (textures, om models, effects) instead
   of embedding them: smaller packages, faster transfer, no game files in shared maps. Compiler dedupes:
   embed only what isn't in the base game.

## Phases
- **P0 compiler + project format**: lp2mapc.py builds today's Area 921 from a project (parity with lp1map).
  Fixes the parked bugs on the way (green: try a stock sky / scheduler set; package size).
- **P1 asset cache + viewer**: open a project / stock map, fly around, see stage + markers with real models.
- **P2 marker editing**: place / move spawns, VS, weapons, posts, camera; layouts 1-4; map info; export -> play.
  (Replaces the Blender marker workflow; first release to testers.)
- **P3 prefabs + collision + painting** (+ ObjSet instancing research).
- **P4 environment**: sky, lights, fog, water, sound nodes, volumes (+ DLL volumes).
- **P5 navmesh** view / edit / generate + bot match support.
- **P6 dynamic objects, lighting bake / preview polish.**

## Research list (blocks parts of the above)
- LP2 data post / flag / pickup object classes and model ids; dynamic object classes (tanks, crushers).
- ObjSet objects with their own collision (runtime instancing).
- Sound node placement format; fog fields; water surface (o00water / on00_suimen / online_water effect).
- Spot light limit per Light scheduler; lightmap vs vertex light in the stage format.
- Collision material ids (DEEP_SNOW sinking, WATER) in rCollision faces + havok materials.

## Progress 2026-10-22 (evening)
- P0 done: lp2project.py (project format + LP1 importer), lp2mapc.py (compiler). Parity: import + compile of s921
  == old lp1map output (512 arc entries, 0 differ); lp1map.py is now import + compile (same output, --project
  keeps the project). lp2light --water CM (mWaterExist + mWaterHeight). Fixed: lp1map's water-plane stub path.
- P1/P2 first build: ~/Projects/lp2-editor (Godot 4.7 GDScript; run.sh, app menu entry). lp2preview.py writes
  PROJECT/.preview/stage.glb (stage via lp2stage, BM textures as PNG, baked light as COLOR_0). Editor: fly cam,
  baked / lit shading, markers per layout 1-4 + set, screen-space picking, drag on ground, inspector, map info,
  water, save, export (lp2mapc), install (backup). Save round-trip: no type changes; positions differ only past
  f32 precision. Test project: ~/Projects/LostPlanet2Maps/Ports/Area921 (raw LP1 import, NOT the installed
  Area921 layout).
- Next: add / delete / duplicate markers (lp2layout record cloning), marker models from the game (asset cache),
  stock LP2 map import, undo.

## Progress 2026-10-22 (late): level geometry, outliner groups, gizmo, prefabs, progress, performance
- lp2pieces.py: stage -> atoms (welded connected parts; 9245 on s921) -> default pieces (boxes + 0.5 m touch;
  261), each splitting into touching groups, then atoms. Applies geometry.json (xf / hidden / copies) to the
  built stage (lp2stage.write_stage, factored out; output byte-identical) and to the LP1 collision (each
  collision triangle follows the nearest visual atom within 4 m). Havok physics is left as built (MOPP), unless
  collision.rebuild_physics (2026-10-23: lp2mopp.py writes a new MOPP tree; editor checkbox; untested in game).
- lp2preview.py now writes .preview/geo.json + geo.bin + tex/*.png (blocks by atom and material, atom
  boxes, default tree, stats incl. the stock map's stage bytes as the memory target). stage.glb is gone.
- Tools print '@progress F TEXT'; lp2mapc.tool() passes children's progress on, mapped into a range.
- Editor: geometry.gd (pieces, group / ungroup / duplicate / delete / reset / prefabs, snapshots for undo),
  gizmo.gd (move / rotate / scale, world axes, Ctrl snap), outliner categories, click-only selection,
  multi-select, progress bar, memory strip + performance panel. Test switches: --selftest, --piece N, --lift M.
- Game asset prefabs (asked for): LP1 maps' pieces are doable by adding the other map's stage model to
  stage.lp1_models with its atoms hidden except the ones used, plus pruning unused materials / textures in
  write_stage. LP2 stock objects need an LP2 rModel (non-stage formats) -> preview + stage-merge path.

## Progress 2026-10-23
- Editor: selection wireframe (feature edges, geometry.wire_mesh), floating Browser window (B; real OS window,
  embed_subwindows off): Prefabs / In the level / Game assets tabs with thumbnails (thumbs.gd off-screen viewport).
- Kill floor: project environment.kill_floor (cm), red sheet in the editor. Game side needs the DLL map volumes (bugs 12).
- Asset library: lp2library.py get --game G [--lp1 L] LIB -> LIB/lp2/<key>.glb + index.json (143: 115 VS, 25 weapons,
  3 posts; ~200 MB, 256 px textures). Editor: library.gd, markers show their model (vs50 -> vs_50, om71xx -> om_7100),
  Browser > Game assets (groups, filter, Get assets button runs the tool). Weapons wp_02/04/05/64: grey (UVs in an
  undecoded vertex format). Model facing vs marker yaw unverified.
- LP1 PC (Steam) vs 360: same map s900, textures 92 vs 81 MB for the same 421, models identical -> no real
  resolution gain. Characters in lp2-assets/lp1/src were already PC rips; Colonies maps (s91x/s92x, Area921) and
  hm70-74 exist only on the 360 disc. Rule: import a map from the PC install when it has it.

## Roadmap (user requests 2026-10-23), in order
Done 2026-10-23: step 1; physics rebuild option (lp2mopp.py: MOPP bytecode decoded from havs921 and verified by
centroid queries; writer uses axis splits / bounds / rescale only, ~1.8x the stock size; edits applied to the
havok mesh like the collision, plus other maps' pieces' tama). Fixed: other maps' pieces got no collision
(foreign_collision passed copies still carrying "map", which apply_collision skips).
1. LP1 map pieces in the Browser (Game assets > LP1 <map>): lp2pieces per map arc (PC first, else 360), thumbnails;
   placing needs the cross-map stage merge (lp1_models + hidden atoms + texture pruning, memory cost shown per piece).
2. LP2 stock objects as placeable props: rModel (scenery) -> stage mesh path in write_stage.
   Done 2026-10-23 (untested in game): lp2props.py -> library map lp2/props (281 om models, one piece each,
   collision = own triangles as SBC1 via lp2col.write_sbc1); Browser group "LP2 objects"; placed via the
   foreign-copy path. copy_meshes groups copies by matrix (a placed piece = 1 mesh per material, not per atom);
   write_stage refuses > 4095 meshes (12-bit group id). Baked light is a fake top light (LIGHT_BASE/UP).
3. Mesh builder (floating panel): import OBJ/glTF -> pieces: mesh, collision (own mesh / box / none -> SBC),
   material per slot. Material builder: colour / normal / mask maps -> DDS (lp2tex), preview in the editor.
   Done 2026-10-23 (untested in game): lp2mesh.py (OBJ + glTF readers, no extra libraries) -> PROJECT/imports/<name>/
   = a small library map ("@project/imports/<name>", lp2pieces.map_folder), one piece per file, collision SBC1 own
   mesh / box / none; source copied to imports/<name>/source/. Materials PROJECT/materials/<name>/ -> rTextures
   um_<name>_bm/_nm/_mm (shared by name, so trim sheets load once). Editor: meshbuilder.gd (M), Browser group
   "Imported meshes"; a rebuild swaps placed copies' atoms (geometry.refresh_import). Also fixed: prune and
   merge_foreign now keep material slot 9 (the environment cube map), which a prune could renumber away.
   To check in game: winding (glTF CCW = LP2 object models' order), the flat NM / black MM defaults on stage
   materials, box collision. LP2 objects (lp2props) still use slot 0 for missing normal / mask maps.
- Lighting (user request 2026-10-23), done (untested in game): editor lighting.gd (L) -> project.json environment
  (sun, sun_colour, sky_colour, ground_colour, ambient, scatter, sky, skybox) + "lights" (point / spot:
  PointLight 0x49A43F8E / SpotLight 0x6A2EC243 objects appended to Light0-3 by lp2light.add_lights). lp2sky.py:
  stock sky models or a panorama dome (Godot panorama u convention) into Scr's online00_car1 slot (mLightGroup 0).
  Fixed in lp2mapc: the v archive never got the Light / Filter / Efc schedulers (case bug). Not exposed: shadow
  regions (Capsule / Point / CuboidShadowRegion), LightSpaceShadow. To check in game: placed lights on the stage
  (vertices carry normals), the car1 sky, the v-archive fix. Toolbar now two rows; tool jobs queue.
- Preview (user 2026-10-23), done: editor preview.gd (P): CharacterBody3D capsule on the stage preview's trimesh,
  over-the-shoulder SpringArm camera, jump / crouch / walk / grapple / step-up; numbers are guesses (settings.cfg
  [preview]). Right-click a light = settings popup. Next: "Preview In Game": export + install + launch, the DLL reads a
  one-shot request (map, mode, start point) and drives the menus into an offline match on it (needs RE of the
  menu / session start; AI Enemy Battle menu +0x19c map row is a lead, see requests-mp-menu.md).
- NEXT, high priority (user 2026-10-23), before the steps below:
  A. Haze / fog settings in the Lighting window: the Filter scheduler's fog (distance fog colour / start / end /
     density, height fog if the stock maps have it: check the uHazeFilter / uNoiseFogFilter / uVolumeNoiseFilter
     classes and the Filter0-3 tracks of every stock map), with presets from stock maps like the light presets.
  B. In-game-accurate preview: make the editor viewport look as close to the game as we can: the game's
     tone curves (ColorCorrectFilter mToneCurve), bloom, scattering haze (mpAreaLScattering Rayleigh / Mie /
     density / sun colour), fog, the sun / hemisphere / ambient model (LP2's shader maths: MT Framework
     lighting), the sky dome as the game draws it, LP2 material maps (normal / mask / specular) and the
     baked stage light. Goal: what you see in the editor = the game, including the green-tint class of bugs
     (Area 921 Lit came out green and with the Desecration windmill: investigate in the same pass).
4. Overrides: replace a map object's model (data posts: om7100 rModel in the map package, if the map's resources
   win over the global uOm arc) and per-placed-VS texture overrides (VS arcs are global: needs the DLL to swap
   textures per instance, or a cloned VS type id per skin).
5. Map volumes in the DLL (kill / damage / T-ENG / water, bugs item 12), then kill_floor = a volume.
6. Visual scripting (node graph in the editor; GraphEdit). First target: a door with a button each side; press ->
   if closed open else close, buttons locked while it moves. Nodes: interact (button), variable, branch/compare,
   timer, move-object (tween), volume on/off. Runtime in the DLL, host-authoritative: host runs the graph,
   broadcasts state changes (door target + start time) over our transport; clients tween locally. Needs: a
   movable collision object (stage props are static: find LP2 movers - the online00_car / scheduler path) and
   an interact prompt hook.
- User 2026-10-23: the campaign has synced button presses, automatic doors and volumes (it is playable in online
  co-op), so the game already has networked gimmicks to reverse and reuse for scripting/doors; at least one MP map
  has volumes that push the character and crushers (user to name it). VS skins: DLL swaps textures when the VS is
  created (preferred). Large address aware (4 GB for the 32-bit exe) will be needed at some point (memory).
- PC LP1 map archives (Steam ZZPack2 s8xx/s90x): lp1points.py fails "not an LP1 FSO layout" (PC FSO differs from
  the 360 one it was written for). Library imports use an empty layout; a PC map project import needs this fixed.
- User 2026-10-23: "Friction" (10th MP menu entry, likely index 9 -> aArea_ONLINE_09?) has crushers, conveyors and
  kill boxes: the reference for movers / push volumes / kill volumes. Matches the earlier lead: SBC surface flags
  0xe0000000 / 0x44000000 only on ONLINE_06/07/09 (handoff-2026-10-19-map-port.md).
- Step 1 done (2026-10-23, untested in game): LP1 maps in the library (19 + s907: PC s810-s907, 360 s920-s923),
  ~2.7 GB (LIB/lp1/<sid>: assets/lp1 raw + .preview incl. the built stage). Browser > Game assets > "LP1 map sXXX"
  lists its default pieces (tooltip: tris, +MB textures); double-click places a copy (member "map": "lp1/s900").
  Compiler: lp2mapc --library LIB; lp2pieces.merge_foreign (meshes, materials with renumbered texture slots,
  rTextures copied into the stage dir) + foreign_collision (that map's SBC, same nearest-atom rule). Test: s920
  piece (1406 atoms) into Area921 -> 111 textures, +29 MB package, all textures present in the arc.
  Memory bar counts borrowed textures (geo.json materials[].textures {name: bytes}, lp2preview.add_texture_sizes).
- Fixes found on the way: PC LP1 textures with D3DFMT 21/22 (A8R8G8B8, s907) decode in lp2stage.tex_rgba; LP1 colour
  maps whose alpha is 0 everywhere (44 of s900's) are masks, not transparency: lp2stage makes them opaque DXT1
  (were DXT5: double memory, black previews, maybe cut away in game).

## 2026-10-23: burial + VS poses (UNTESTED in game)
- Burial is per record, not per item: objset +0x7c pile model (0 om8100, 1 om8103, 2 om8104), +0x80 digs to uncover
  (0 = not buried), +0x84 sink depth, +0x88 pile height = cObjSetDataBase mUserData[2..5] -> object mUserWork[2..5],
  read by uWeapon::vf5 (0xc73df0) and uVitalSuit::vf5 (VS can be buried too; stock VS digs 10-100). +0x04 is
  controlStatus (VS have 10 / 20 too), NOT burial: the 2026-10-23 "tier 0" fix for #5 was reverted.
- #5 real cause: Battlegrounds is built on Desecration, whose records hold 50 buried items; lp2layout kept the dig
  fields. put_dig now writes them from the marker ("dig", "dig_pile") or clears them (weapons and VS, both paths).
- Editor: "Buried: digs" + pile choice in the inspector for selected pickups / VS.
- VS poses: lp2pose.py (LMT v0x38: track 0x24 bytes, ref = first key, extremes = range then min). Motion 0 first frame
  for every VS, position tracks far from the bone offset skipped (IK targets: applying them "mashed" the models);
  > 60 cm under -> bind pose; anything under the origin lifted onto it. Arms stay out on IK-armed types (vs00, 50, 07,
  2a, 41, 42); vs_e3 / e4 still messy. Weapon names: MsgCommon (ID_FCORE_EN_PC.arc) block 1, descriptions MsgCinesco.
- Explicit pickups (2026-10-23, UNTESTED): editor "Pickup" chooser -> marker "item" -> lp2layout writes +0x1A on both
  paths. Fixed infantry ids with archives: 00-06, 0D-14 (names by MsgCommon order, likely but unconfirmed). 08 / 0A /
  0C / 15-19 / 30-34 / 40 / 41 / 43 / 44 / 6E have empty archives (slots or loadout-only). Heavy weapons: Heavy slot only.
- Soldier animation in Blender: lp2_blender_anim.py (lp2pose.tracks_keys: every buffer type, keys = frames to next).
  Machine gun pack: lp2-assets/weapons/wp00/.

## Requests (user 2026-10-23, later)
- Animation preview app: play common LP2 animations (run, aim, crouch, grapple, roll...) on a custom part set
  BEFORE it goes into the game, to catch rigging / weight errors. Start from what we have:
  lp2_blender_anim.py already samples game motions (lp2pose) onto LP2_rig in Blender; options: a Blender add-on
  panel (pick set + motion, play), or a viewer in the Godot editor (glTF of the set + baked motions).
- Bones now have readable names (lp2bones.py; exporter reads names, aliases and jNNN); bare skeleton
  skeleton/lp2_skeleton.blend (lp2_skeleton.py make / rename). snowbunny.blend renamed 2026-10-23 (export
  byte-identical); custom joint ids now deterministic (sorted by depth, name).

- 2026-10-25: Place tool (T, place.gd): floating window, Spawn / Weapon / VS dropdowns (VS list from notes/vs-ids.md),
  click = ray onto the stage, drag = yaw on the level plane (Ctrl/Snap 15°). Markers get "placed": true and can be
  deleted. lp2layout.patch_objset clones extra VS / weapons from the group's first record (placed VS type = model).
  Spawns beyond the stock rInitPosSet counts are still not exported (no writer). Test: main.gd --screenshot X --place.
  Untested in game.

## 2026-10-26: fog window, pan, game types, preview start
- Fog (H): environment.fog {on, start, end (cm), colour, density, height_on, height_top, height_bottom (cm),
  height_colour, height_density}; lp2scenebox.from_project -> every zone's fog record (stock curves, type 4).
  Presets = stock maps' priority-15 zone. View: Godot depth fog + height fog (approximation).
- Middle drag pans the camera (grabbed point follows the mouse).
- Sets: "modes" = LP2 game types exported from that set (lp2layout.layout_for); the '0V' set takes every
  type no other set of the variant claims. Markers: "modes" (absent = all); inspector shows "Exists on".
- Preview (P) starts on the spawn nearest the view's target; Place list: 29 more VS types (Akrid 0x1a/0xd4,
  model fallback to any model\ folder; mod2obj resolve_ci tries every case spelling).

## 2026-10-26 (later): collision view, install = export, weather
- View collision (toggle): lp2colview.py PROJECT OUT.bin [--geometry FILE] -> movement collision with edits.
- Install to game: save + export + copy (no .bak in the game folder). Place: "all 4 layouts" copies.
- Map info: floating window (I).
- Weather (lp2weather.py, environment.weather {type rain|rain_heavy|snow|ash, amount, layouts[4], volumes}):
  ScrList type-16 entry (effect list, mPara1 slot) + its resources copied from the stock map (arcput --add;
  efc_tex ls000N are resident); every zone weather [1,100,kind]; volumes = box zones (shape 0x10, prio 7,
  weather [1,0,0]) added to the grid cells (cell = zi*32+xi) they cover; Efc0-3 mWeatherRate = amount
  (per layout if Efc N = layout N: untested). Match Weather rule may override. UNTESTED in game.
- Next asked: publish the custom map's name to players without the package (browser + lobby show DUMMY ####;
  no refresh after download) -> xlive maps.cpp name lookup (MsgOnline 126 + slot) + session/lobby data.

## 2026-10-26: custom map names for players without the package (xlive, built, NOT installed/tested)
- Host publishes "13=<name>\n14=<name>": member data "mapnames" (packages.cpp NamesValue) and appended to
  QoS answers after the title data (core/net.cpp QosExtra 'LP2X' + u16 size; older builds read only
  dataSize, so compatible both ways). Clients keep (QoS data, text) pairs: NetQosExtraFor.
- Lobby: PackagesSlotName prefers the lobby host's published name (g_lobbyHost from Reconcile).
- Browser: the detail panel DX9 FUN_00e82360 / DX11 0xe92430 (thiscall(screen, entry); entries at
  [screen+0x5c8]+0x288 + i*0x94 = the host's QoS data, map at +0x290+0x51) is detoured; while it runs the
  MsgOnline 139/140 lookup answers with the name sent with that entry's QoS data. List rows show no map.
- Lobby map vote (FUN_00e77f60) and results (FUN_00e78e00) go through the same lookup.

## 2026-10-26: VS preload, pickup labels, collision pick / from mesh (untested in game)
- No VS on custom maps: the game preloads VS / weapon archives from a hardcoded per-map list (DX9 0x1720f90,
  {arcs, area 7, map}; arcs = {char* name, u32 flags} split by "dummy" into a common group + one group per
  mode x layout, FUN_007c5570 / FUN_007c24b0). Map 00 has none of LP1's 0x50/51/53/56 or 0xe3, so they never
  spawned. Fix: map.json "preload" (lp2mapc.preload_arcs: every VS / mounted weapon / pickup the objsets use);
  xlive maps.cpp WithExtras appends the missing ones to the slot's common group (both exes via kDepRvas).
- "VS on map" = objset +0x04 tier (0 / 10 / 20; None, then +tiers up to All). Ride id 0x0122 logged for the
  flyer = Controls didn't see a VS (no archive loaded): retest fly controls after the preload fix.
- LP1 weapon markers keep the stock record's pickup by index, which differs per game type file; k40 points
  then FFA starts take the stock file's extra records. Editor labels now say so (pick a pickup to fix it).
- Kill floor: editor setting exists, game ignores it. No stock mechanism found yet (map 00 AreaHit = radar
  zones only; abyss camera via body +0xd6c bit 15 set from uControl::vf21). Needs the player health / a kill
  call: find at runtime (fall to death on a stock map with pits, diff the body).
- lp2colview.py writes per-triangle owners (atom, or -2-k for copy k); editor picks the piece under a click
  when View collision is on (layer 3 trimesh, face_index).
- Geometry tree "mesh_collision": true -> lp2pieces.mesh_collision / mesh_groups: the piece's imported
  collision dropped, its visible triangles added (move + bullet + havok, all via apply_collision). Foreign
  (other map) copies don't take it yet. Inspector: "Collision from mesh".
- 2026-10-26 (later): VS tier rule decoded, DX9 FUN_00f71410 (rules +0x256 == 1, setting at DAT_018427b0+0x44):
  setting 1 (None) hides all; 2 (Few) shows tier 0 only; 0 (Many) hides tier 20; 3 (All) shows all. Weapons:
  FUN_00f71490 (+0x3c: 1 none, 2 / 0 tiers like VS, 4-7 force pickups < 0x35 to slot 0x30-0x33). Editor tier
  dropdown labels follow this. In-game test still showed tier 0/10 VS missing: unexplained (pairs 2-4 m apart?).
  LP1 VS records have u32 +0x08 = 0 / 1 (one of each near pair): probably LP1's VS-amount level, dropped by
  lp1points.py -> should become the LP2 tier in the conversion pass. No stock LP2 objset uses VS 0x50/51/53/56/e3.
  uWp00 = Anchor (grappling hook, "Anchor(uWp00)"); Machine Gun = uWp01. Editor PICKUP_ITEMS ids are wrong
  (loadout message order, not weapon kinds). wp blend for skinning: lp2-assets/weapons/wp01.
- 2026-10-26 conversion pass done: lp2convert.py (also lp2project.py import-lp1 --game): LP1 VS pairs ("lp1_pair"
  from lp1points +0x04) -> pair 0 only; VS tiers vs50/51 0, vs53 10; vs56 -> weapon 0x1f (flying gear); LP1 weapons
  -> slots / grenade slots (LP1_WEAPONS), VS weapons keep id if uWpXX.arc exists; the stock Team file's leftover
  weapon records baked as weapon markers on k40 then starts (item + tier); "explicit" on layout + sets ->
  lp2layout adds no point pickups. Area921 converted (88 VS dropped, 396 pickups). Editor PICKUP_ITEMS rewritten
  (0x00 Anchor removed, fixed names = guesses), pickup markers show the item's library model (wp_XX).
  VS weapon names (user, in game): 0x61 VS Rocket Pod, 0x62 VS Pile Bunker. Models hold 2-4 copies (one bone tree each).
- Weapon id -> MsgCommon name index: DX9 FUN_008a1980 (u32 id 0x04KK00VV: KK kind, VV loadout variant). 0x0a T-ENG
  Supplier, 0x0c Handgun, 0x15-0x19 x variant 0-4 = grenade families, 0x1a-0x23 all "Battle Armor" (gear),
  0x30-0x34 x variant 0-6 = the loadout weapons (0x30/0 Machine Gun ...), VS: 41 Gatling, 42 Laser Rifle, 43 Rocket
  Launcher, 44 Shotgun, 45 Grenade Launcher, 46 EM Laser, 47 Homing Laser, 60 Pile Bunker, 61 Rocket Pod,
  62 Laser Lance, 63 Rifle, 6a 199-201. Unnamed (VS-only): 4e Missile Launcher (user), 50, 4d, 64-69, 6d...
  User confirmed: 0x4E VS Missile Launcher (VS only), 0x47 Homing Laser; a VS-only 'missile pod' also exists (id not yet matched).

## 2026-10-26: release builds (Windows zip + Linux AppImage), public repo lp2-mapedit
- Bundled: Godot export + python-build-standalone 3.12 (numpy, Pillow) + the editor's lp2-tools closure (tools/).
  ImageMagick dropped (tex2dds.dds_png, Pillow). runtool.py replaces the `sh -c 2>&1` wrapper.
- Editor: Settings window (LP2 / LP1 / library folders, Steam auto-detect, first-run), New... (import an LP1 map).
- ROADMAP (user, soon): wire all LP1 VS logic back in. Users building in the editor may place LP1 VS (vs50/51/53/56
  and the rest of LP1's VS), and today vs56 doesn't work as a ride and only stock-LP2-used VS are known good.

## 2026-10-27: ROADMAP (user): Kill Confirmed mode (rules mod, alongside Survival)
- Design (user): a death drops a dog tag. An enemy touching it = confirm (team point), an ally touching it = deny.
  Player score = kills + confirms + denies; the team score (what wins) = confirms only. Tags are touch volumes
  (no button pickup) with easy-to-read ally/enemy colours (per viewer: ally vs enemy, not team A/B). Tags time out.
- Plan: ride the Points rule (3 Points / 6 Team Points: per-player + team points, Points scoreboard column, cap 255).
  Rules string key confirmed=1, lobby-gated like Survival (rule 3/6 only), create-screen row like Survival's.
  Hook the rule 3/6 branch of the kill handler DX9 FUN_00f6b620: no stock steal; killer +1 player score, spawn tag.
- Step 1 findings (decompile, 2026-10-27):
  - Kills are replicated as net actions: cNetAct::vf13 (send) / vf28 (receive) -> FUN_008c7f90 -> FUN_00f6b620 on
    every machine, so points are computed locally everywhere from the same kill events (deterministic hook OK).
  - No touch pickup to reuse: sItemManager (DX9 vf3 0x805da0, size 0xbcd0) only tracks Weapon, Bomb (per player),
    DataPost, VitalSuit, Akrid, ObjectModel; weapons need an active pickup. T-ENG is ability params, no item class.
  - So tags are ours: tag list in the DLL (id, pos, victim team, expiry), proximity test each frame against player
    positions; the host decides confirm/deny (first touch wins) and broadcasts on our Steam control channel
    (core/net.cpp kControlChannel; transfer.cpp has 0x10001), applying the score via the points setters.
  - Open: the visual. Need a runtime way to draw a coloured marker at a world position: a game effect spawn
    (EFL), an object model, or reuse the Data Post beacon look; else a D3D overlay billboard (we have no world
    draw yet). Next step: find an effect/model spawn call taking position + colour.

## 2026-10-27: ROADMAP ideas (user)
- **Mod options sub-menus**: plugins register pages (header + rows: toggle / choice / slider / key bind, values saved
  per plugin) through the plugin API; the DLL adds an Options -> "Mods" entry with a sub-page per plugin; the list
  scrolls (or pages with the shoulder buttons) when long. Controls + DevTools first (DevTools leaves its json).
  Unknown: whether the game's options list has fixed slots / can scroll (decompile pass, DX9 + DX11 dumps).
- **Lighting (pipe dream)**: real ray tracing is out (RTX Remix = DX9 fixed-function era, LP2 is all shaders; DX11
  predates DXR; our own tracer = months). Realistic: recommend a ReShade preset (SSAO / SSGI), raise the sun
  shadow map size / distance from the DLL, raise the dynamic light cap / shadowed lights if the shaders allow.
- **Terrain builder (editor)**: heightmap terrain in chunks (65535-vertex collision groups), sculpt brushes
  (raise / lower / smooth / flatten / ramp), holes (cell mask: caves, tunnels with placed meshes), paint layers,
  and auto-paint by slope (e.g. 0-30 deg snow / sand fading to rock on cliffs) and height. Built into normal
  meshes + collision (surface flags per layer: snow = DEEP_SNOW, etc.), later the navmesh. Open: how the game
  draws the blend. Check whether stock stages have a multi-layer / vertex-colour blend shader; else bake the
  painted result into per-chunk textures (memory cost) or split chunks by dominant material.
- **Surface painter (editor, needed anyway; shares the terrain builder's brush)**: paint collision faces with game
  surface tags: material (footsteps / effects / sinking: SNOW, DEEP_SNOW, ICE, SAND, METAL, WATER, LAVA, ... the
  exe's ground list, see bugs-2026-10-21 #10) and behaviour bits (grapple-able or not, and whatever else the
  flags hold). Per face in the project, written into the sbc surface flags (lp2col: 0x3fffff00 plain,
  0x8000xxxx material bits; today every face gets one flags value). Overlay view colours faces by tag.
  Prereq: decode the flag bits from stock rCollision (snowy campaign area for DEEP_SNOW; a stage with
  non-grapple walls), DX9 + DX11 dumps for the readers.

## 2026-10-27: VS families + weapon mounts in the editor (lp2vsfamilies.py -> vs_families.json; editor vsprops.gd)
- Place: one entry per base-model family (41); inspector: Variant (the family's LP2 types), Right / Left arm weapon
  (only mounts with a joint 100 / 101), shoulders shown as built-in. Marker "weapons": [[fitted, id] x4]; absent =
  the type's stock loadout at build time (lp2layout.put_weapons). See notes/vs-mounts.md.

## 2026-10-27: ROADMAP (user): additional VS weapons, first a Welding Beam
- Hold to fire, continuous damaging beam, drains T-ENG while firing, can overheat.
- Viability (not researched yet): the exe's weapon classes are fixed, so a new weapon = a new weapon id whose archive
  reuses an existing class (a beam / laser one: 0x46 EM Laser, 0x47 Homing Laser, 0x62 Laser Lance) with new params /
  effects, plus DLL hooks for what no class does (T-ENG drain per frame while firing; heat if no class has it).
  New ids need registering like the parts carrier slots. First step: decompile the VS laser weapon classes (fire
  modes, heat / energy fields in fields.tsv) and list what each already supports.
- (2026-10-28) Boss GTF-11 (vs40 on 0x82, notes/vs-ids.md): its left-hand custom laser (hard-locked) and the leg
  rocket launchers are model geometry today; give them real weapon types (same research as the Welding Beam).

## 2026-10-28: ray-traced lighting bake (lp2bake.py) — built, untested in game
- lp2bake.py (Embree via pip embreex): sun (soft shadows), sky + ground, placed point/spot lights (start/end fade,
  cone + soft edge, shadowed), glowing materials (stage.light.emissive {colour map: rgb}; no UI yet), N bounces with
  material average albedo. Per-vertex (the stage format has no lightmap UV). Rays start spread over each vertex's
  surrounding triangles (else floors at wall feet all shadowed); back-face hits = sample discarded (origin inside
  geometry); LP1's sky dome (>2 km out) excluded and keeps its colour; seams averaged.
- Components stored apart (sun/sky/ground white, lights, glow; bounces included) -> .preview/bake.bin as CUSTOM0-3;
  baked.gdshader combines them live (sun/sky/lights/glow strength, exposure, min light, env colours). Rebake for
  geometry / light placement / sun direction / bounces / samples. Battlegrounds: ~26 s, 1.4 GB RAM.
- Light model assumption: vertex colour c is gamma-space light, pixel = tex x (2c)^2.2 (also fixed in the editor's
  baked shader; interiors used to show mid grey). CALIBRATION 0.48 = Battlegrounds default bake median = LP1's.
- Hooks: Lighting window "Baked lighting" (source LP1/bake, sliders, Bake button); lp2preview re-bakes a rebuilt
  preview; lp2mapc bakes the final stage (after geometry edits) when source = bake. Preview key ignores stage.light.
- Detail (stage.light.detail = +% vertices): quick bakes (16 rays, 1 bounce) find triangles whose corners' light
  differs > 1.5x, split their longest edge (and every triangle sharing it), up to 3 passes, then the full bake.
  Preview keeps the unsplit geometry in .preview/geo_base.*; the build splits the final stage (tangents / w bytes
  carried; write_stage splits meshes past 64K). Battlegrounds +30%: +81k vertices, preview 63 s, package 39.1 -> 41.1 MB.
- TODO: in-game check of the gamma assumption; emissive material picker UI; add embreex to the release PKGS (cp312
  wheels: check Windows); triangle splitting for sharper shadows (phase 3); bake_btn stays disabled if the bake fails.
- Editor tests run headless: gamescope --backend headless + --screenshot (low_processor_mode is off for screenshots).

## Backlog: "we'll get back to it" (user, 2026-10-28)
- Handgun class (user, 2026-10-28): the stock game never has handgun pickups (one campaign mission gives it as a
  spawn weapon); we add placeable handguns to MP as a QOL change, later as their own class with sub-options (default
  pistol, heavy pistol, SMG). The editor shows 0x0c as the default handgun (Wp0c). The importer writes 0x0c records
  (14 on Battlegrounds): check where those come from in the importer/decompile pass.
- Map thumbnails in Create Match: still not showing for custom maps (DLL ID221_SC<slot>_ID swap from
  handoff-2026-10-19-map-port.md / lp2thumb.py). Re-test, then find why.
- Start camera (the match-intro / pre-spawn camera, project environment.camera): still not taking effect in game.
- Havok world box: NOT the z-kill (2026-10-28, DX9). FUN_007ff3a0 builds the hkpWorldCinfo (ctor FUN_01064ac0;
  layout from the exe's hkClass members: gravity +0x10, broadPhaseQuerySize +0x20, broadPhaseBorderBehaviour +0x28,
  broadPhaseWorldAabb +0x30/+0x40, collisionTolerance +0x54), setBroadPhaseWorldSize(FUN_01064c90, DAT_016e73cc =
  30000.0) -> AABB -15000..15000 Havok units, border = 2 (REMOVE_ENTITY). Game -> Havok is cm * 0.01
  (DAT_0135b6bc), gravity -9.8 (DAT_016e7408): the box is +-15 km on every map, a single constant, never reached.
- Kill floor / fall death: SOLVED at runtime 2026-10-28 (DX9, NEOS). uCharacterBase::vf49 (0x9c3fb0) casts a
  collision ray down from the character (FUN_009b51a0 -> FUN_004c15d0, sCollision::TriangleInfo) and takes the hit
  triangle's surface attribute (FUN_0082fe30(2) = surface record u32 word 3); FUN_009ab9e0: attr & 0x700 -> lethal,
  FUN_009aba20 kills (health setter 0x9aba8b, health = char+0x18c8 XOR [DAT_018427b0]+0x1f58; char =
  *(*(*(*0x01842020+0x28)+0x484)+0x200)). Death logged at y -78.8 m; the floor is at -81 m.
  Stock data: the TAMA (bullet) rCollision holds a flat 2-triangle quad with a surface whose word 3 = 0x200
  (other surfaces: 0..0xf, 0x2003, 0xff on atari): ONLINE_00/02/05/07/10 2 tris, 01 18 tris, 06 0x100 x32 tris;
  03/04/08/09/11/12/15 none. NEOS: y -8100 cm, x -51000..-9500, z -23000..23000.
  Editor: kill volume = add a surface (word 3 = 0x200) + its triangles to the tama collision (lp2col / apply_
  collision); a box = its top face (or all 6 faces). LP1 imports need one too (map-wide quad below the lowest point).
- Volume types wanted (user): kill zone, low gravity (affecting everything: characters, Havok, grenades), boost
  pack (NEOS: short horizontal air boost) as a map option.
- Gravity + volumes IMPLEMENTED 2026-10-28 (untested in game): xlive src/mods/gravity.cpp wraps the per-area flag
  table call (DX9 FUN_00869940 @ call RVA 0x46c10e / DX11 0x478ff0 @ 0x47b7be; table: episode +0x257 7 = online,
  area +0x25a; online 7 -> flag n6 low gravity, online 2/3/5/6/8/11 -> n5 underwater) and the character gravity
  update call (DX9 FUN_009acef0 @ 0x5ae4bd, mGravity +0x17bc; DX11 0x5bc860 @ 0x5bde2d, +0x17cc). map.json
  low_gravity / underwater / gravity (also scales [main]+0x511d0 Havok world gravity) / gravity_volumes (boxes,
  cm). Editor: Map info checkboxes + Gravity x; volumes.gd (project "volumes": kill / gravity boxes; kill = 0x200
  quad over the box top, lp2mapc). Grenades / projectiles: not yet (own uShell gravity).
- Backlog (user): volume colour grading / "underwater visuals" per area (tone map tweak inside a volume): needs
  the game's post-process hook.
- Low gravity, decoded 2026-10-28 (DX9, runtime on NEOS): CHARACTERS only. FUN_009acef0: cJump mGravity
  (char+0x17bc) = mGravityOrg (+0x17c0) x factor from stage flags [DAT_018c080c]+0x14598 (bits set as
  0x80000000 >> n, setter FUN_0083e700 / clear 0x7c...): 0x02000000 (n 6) -> x0.3 map-wide (_DAT_0135b19c);
  0x04000000 (n 5) + FUN_007edf20(pos) zone test -> x0.8 / 0.7 / 0.5 / 0.4 (DAT_016e73ec / 7488 / 01356e8c /
  016e72f8; by +0x17b4 sign and FUN_009a1bf0 == 2). NEOS flags 0x0a010000 (n 4, 6, 15): n 4 = boost pack? Who
  sets them at load: unknown (write-watch stage+0x14598 across a NEOS load).
  Havok world gravity: [DAT_01842020]+0x511d0 vec, (0,-9.8,0) on every map incl. NEOS, read by FUN_007ff3a0 when
  the world is built -> per-map DLL write before that. Grenades/projectiles: own uShell mGravity per class (NEOS
  grenades arc normally) -> DLL hook. Plan: map.json gravity -> DLL sets the stage flag/factor, world gravity
  and a shell scale.
- Bike pickups inside Battlegrounds buildings (2026-10-30, FIXED, untested in game): not an LP1 id mapping. LP1's
  Colonies layouts hold only ~60 ordinary weapons; every other weapon marker is lp2convert's fill of LP1's k40 points
  + FFA starts with Desecration's stock Team records in order, which include the vsd1 bike gear (items 0x1D / 1F /
  21 / 23; 0x1C / 1E / 20 / 22 are energy cores). lp2convert GEAR: the fill skips them, fix_gear turns ones already
  on k40 / start points into Slot: Standard (0x30). Applied: Area921 41 (8 elsewhere kept), Battlegrounds 57,
  BattlegroundsBoss 57, CrossfireCity 56; packages rebuilt + installed. LP1 PC (Steam: ~/.local/share/Steam/
  steamapps/common/lost planet extreme condition, x86, unpacked, DTI names) is there for later RE.
- Detail budget counts vertices; triangles grow ~2x faster (100% = 2.5x tris): budget by triangles instead.

## 2026-10-28 later: volumes rework, post-process, jump packs
- Volumes: own outliner category; combinable effects per box: kill / gravity / post / no_weather (old "type" and
  environment.weather.volumes migrate on open). Ctrl+drag a face pushes/pulls it (Shift snaps).
- Post-process volumes: xlive post.cpp adds its own uPlanetColorCorrectFilter (factory DX9 0x7bf970 / DX11 0x7ce7f0,
  sUnit [0x18c0c30]/[0x18d0cd0] add 0x4a0740/0x4a1900 line 6), vtable copy with vf6/vf0 ours; correctors 8 (rgb
  multiply), 5 (saturation, 0.5 = 1), 9 (levels). Camera: sCamera [0x18c0c3c]/[0x18d0cdc] +0x34 -> +0x40. UNTESTED.
- "Low gravity" is now "jump_packs" (flag 0x02000000 with the game's x0.3 undone; map gravity decides).
- Thumbnail in game: BLOCKED, the id221 Flash's mc_monitor frames for maps 13/14 are empty (packages.cpp
  GenerateThumbnails is disabled). Needs a GFx edit giving those frames a picture (rules.cpp already edits id221).
- Fog (distance + ground) reported not rendering in game: investigate.
- Gravity volume test was at map gravity 0.045 (0.15 x low 0.3): x2 hard to notice; DLL now logs entering a volume.
- Volume effects are settings on one box (post-process is one of them, a "post-process volume" = only that ticked).
  Future effects to add the same way: damage over time, heat regen (thermal energy) zones.
- Place window: kind "Volume" (effect dropdown), click = 10 m box, drag = floor rectangle.
- 2026-10-28 test: gravity volume works in game (logged entry). Post filter: made twice (character updates run on
  several threads) -> double grade + flicker; fixed with an interlocked owner flag. Neutral grade now settles
  exactly (identity matrix + default curves/gamma = the game skips the filter's draw).
- Backlog: audio volumes (muffling / reverb / low-pass inside a box, e.g. underwater) as another volume setting.
- DONE (untested on Windows): rebuild preview 31 s -> 3.5 s (Battlegrounds). lp2stage: textures + lightmaps cached
  by source hash (~/.cache/lp2-tools/stage-tex, %LOCALAPPDATA% on Windows; bump TEX_VERSION when lp2tex changes),
  made in a process pool; vertex packing + balance in numpy. Output byte-identical to before. lp2preview PNGs in a
  thread pool. Left: lp2pieces.default_tree ~1.9 s. GPU only worth it for Bake lighting.

## Export speed (2026-10-28)
- Caches (~/.cache/lp2-tools: stage-tex, bake, collision) + cores: Battlegrounds cold export ~125 s -> 63 s, warm 12 s,
  output byte-identical. lp2bake: rays split over a thread pool (embree releases the GIL), bounces gathered for all lit
  components at once (CSR rows over threads), threaded setup. lp2pieces: atom grid built once per collision file
  (was per group: 78x), per-cell search threaded. Windows bundle still to test (thread pool, no new packages).
- Later (user, 2026-10-28): shadow maps beat vertex lighting for sharp shadows; or use shadow-map-style sun
  visibility to decide where the detail pass adds vertices (split along real shadow edges, not vertex contrast).
- Next steps in order (user, 2026-10-28): see notes/handoff-2026-10-28-next.md: shadow-map vertex splitting, detail
  above 100% with a memory warning, import LP2 assets, sound volumes, particle zones & emitters, sound nodes, random
  logic for both (timing, offsets, volume, pitch... as ranges).

## 2026-10-30: project location
- LP1 port projects (Area921, Battlegrounds, BattlegroundsBoss, CrossfireCity) moved from lp2-assets/projects to
  ~/Projects/LostPlanet2Maps/Ports (user's choice). Older notes (bugs-2026-10-21-mp-test.md) keep the old path.

## 2026-10-30: weapon drop mapping, settled
- LP2 tree (dx11 classes.txt): uWp08 grenade base -> 15-19 grenades; uWp1a -> 1c/1e/20/22 energy cores; uWp1b ->
  1d/1f/21/23 vsd1 bike gear; uWpCategory -> 30-34 loadout-slot pickups; 41-47 / 60-6E VS weapons.
- LP1 PC tree (ghidra/dti scan.py + names.py on LostPlanetDX9.exe): uWp00-08, 40-50, 5f; Colonies (360) adds 0c, 0d,
  0e, 0f, 60-63. LP1 weapon id = record byte 0x1a (BE high byte), sub-type in 0x1b (grenade kinds: wp_08xx sound
  banks 01/08/0b/14/16); every Colonies layout uses 0800. No LP1 layout (s900, s920-923) has anything in 15-1f / 30-34.
- Audit of the 4 ports after fix_gear: every LP1-origin drop matches lp2convert's rules; the rest are the stock fill
  (grenades, slots, cores, 0x0c, VS weapons). Area921's 8 off-point bike gears (2 spots x 4 sets) were old fills too
  -> Slot: Standard. LP1 Colonies 0c pistol -> 0x0c handgun, 0d revolver -> 0x31 Short, 0e hand cannon -> 0x33 Heavy, 0f flamethrower ->
  0x31 Short (user identified them from model renders, 2026-10-30; lp2convert LP1_WEAPONS). Open:
  what LP1's k40 points are (LP1 PC exe could say).

## 2026-10-30: sound zones (reverb), first cut
- Stock maps already have reverb zones: Sound\reverb\<area> (rPlanetReverb XFS: presets, 4 cReverbParam I3DL2 each)
  and Sound\seg\reverb\<area>_rv (rSoundSeGenerator SEG v8, 0x2c0 records = LayoutInfo from +0x90; layout in
  lp2sound.py's docstring). A zone = 4 floor corners + height; entering sets preset SET REVERB, leaving SET REVERBOUT.
- lp2sound.py + sound_presets.json (18 stock presets); lp2mapc writes both files when a volume has
  "sound": {"reverb": key} or environment "sound": {"reverb"} is set (map default = preset 0 + a map-wide zone).
  Editor: volume "Reverb" checkbox + preset list (volumes.gd REVERBS). No xlive change.
- Untested in game. Unknowns: SET REVERB = index vs mUniqueID (we write both equal); overlap priority (we put rooms
  before the map-wide zone, as Frozen Wasteland). Not yet: editor UI for the map default, shutout (muffling) zones.

## 2026-10-30: .lpme files, My assets, LP2 import (untested by the user)
- .lpme = zip of the project folder (no .preview / build); the editor unpacks it to user://work/<name>-<md5(path)[:8]>
  (lpme.gd), works there, packs back on every save (worker thread, ~2 s). Old folders still open (pick project.json).
  The 4 ports packed to Ports/*.lpme (folders kept until the user drops them); recent project = Battlegrounds.lpme.
- Toolbar: "Import map from LP/LP2..." (newmap.gd: LP1 arcs or LP2 online maps -> a new .lpme); Mesh builder button
  gone (M still opens it). Browser tab "My assets": folders (project "browser"), prefabs (pf "folder") + custom meshes.
- LP2 import (lp2project.py import-lp2): built like an LP1 port on Desecration, from the asset library's converted
  stage (lp2stockmaps.py) + SBC1 collision, the map's own rHkCollision, layout from its stock files
  (lp2layout.stock_layout), stage.light source bake, its sky / reverb. Kraftwerk builds (107 MB) and opens.
  Open: memory 112 / 67 MB (whole stock stage, over Desecration's budget); bake median light 0.013 (dark?); the
  stock map's gimmicks / effects / music aren't carried (Desecration's music).
- Create-match picture always Desecration: maps without a thumbnail (Area921, BattlegroundsBoss) use the base's,
  and the id221 textures are resident from the title archives, so a rebind while scrolling doesn't change them.
  Fix needs a live texture update on rebind (DLL: find the rTexture, update its D3D9 / D3D11 texture).

## 2026-10-31: ROADMAP (user): terrain editing
- Terrain area: place, select, Ctrl+drag its edges to grow / shrink (volume face-drag code); painted data kept in world
  space, so resizing crops / extends instead of stretching.
- Edit button: lock + grey out everything else, show only the terrain, toolbar: height (raise / lower), smoothing,
  texture paint, texture fill, hole cutting. Brush size + strength, each optionally tied to pen pressure
  (InputEventMouseMotion.pressure).
- Game side open question: does any stock stage material blend layers (mask / vertex weights)? Else bake the painted
  layers into per-chunk textures (memory budget) and give collision faces the dominant layer's surface flags
  (shares the surface painter's flag decoding).
- Collision flags on mesh polygons (user 2026-10-31): tag faces of placed / custom meshes with collision flags, e.g.
  Friction's conveyor belts (find how stock Friction marks them: rCollision face flags vs a gimmick). Same face-tag
  store + overlay as the surface painter.
- Force zones (user 2026-10-31): a volume effect pushing players (grav lifts, underwater currents). Modes: fixed
  direction, or pull toward / push from a target point; strength with a falloff gradient (by distance to the point or
  across the box). DLL side like gravity volumes (InBox per frame, add to the player's velocity), DX9 + DX11.
- Damage over time (user 2026-10-31, "soon"): a volume effect and a surface tag (painted collision faces / mesh
  faces), with separate values for players and VS: per-second damage, or instant kill. Example: LP1 Crimson River's
  lava flows kill players instantly and damage VS heavily over time. Check how LP1/LP2 do lava (surface material
  LAVA in the ground list? a gimmick?) before writing a DLL tick. Heat-regen zones go the same way.

## 2026-10-31: terrain step 1 BUILT (editor-tested + exported, NOT tested in game)
- Editor terrain.gd: "Add terrain" (beside Add volume) = 64 x 64 m flat grid, 2 m cells, at the view's centre. Outliner
  category "Terrain" (walls moved to category 7). Inspector: size X / Z (m, far side), cell size 0.5 / 1 / 2 / 4 m
  (bilinear resample), material (blockout grid or a project material: its colour map shown, tiled by "Texture tile").
  Selected: outline + see-through sides; Ctrl+drag a side (or the ground near an edge, from above) grows / shrinks it
  by whole cells, edge heights carried out, world grid kept (main._face_at routes Ctrl+drag to terrain or volumes).
  Gizmo: move only. Undo snapshots carry the heights (packed arrays); Save writes terrain/<id>.r32.
  Editor shading: unshaded + vertex colours from a fixed sun (terrain.SUN), like the level's baked look.
- Data: project "terrains" [{id, name, pos (cm, grid corner), cell (cm), cells [nx, nz], heights "terrain/<id>.r32",
  material, tile, yaw 0}]; .r32 = (nx+1)(nz+1) float32 cm above pos y, rows along x. Format in lp2terrain.py docstring.
- Compiler lp2terrain.py: builds PROJECT/terrain/<id>/ through lp2mesh.build_import (new d= / mesh= args: triangles
  made in code), placed as "@project/terrain/<id>" copies (identity m, "rev" = build key so collision caches see
  height changes). Blockout material terrain_blockout (green, 1 m). Cached by build.key. lp2mapc: terrains present ->
  physics rebuilt (grenades land on it) even with rebuild_physics off.
- Tested: main.gd --terrain-test (add, Ctrl+drag +x / -z, spike stays in world, undo / redo, save) on a scratch copy
  of Battlegrounds; full export: terrain in stage + bake + move / bullet collision + rebuilt physics (MOPP check ok).
- Seen, not looked into: the pieces path (any geometry edit, now also any terrain) drops 41 move-collision triangles on
  Battlegrounds ("41 dropped"); existing behaviour, check it doesn't open holes.
- Not yet: View collision (lp2colview) and the lighting-bake preview don't include terrain; holes; layers.
- NEXT (step 2): Edit button (lock + grey others, terrain-only), toolbar, brush (size / strength / falloff, pen
  pressure toggles), height raise / lower + smooth, per-stroke undo.

## 2026-10-31: terrain steps 2-4 BUILT (edit mode, brushes, paint / fill, holes; editor-tested + exported, NOT in game)
- Inspector "Edit terrain": other markers hidden, level geometry greyed (material_overlay), gizmo off, selection
  locked (picking anything else in the outliner leaves; Delete / Ctrl+D / Ctrl+G / End blocked); Esc or Done leaves.
  Undo / redo stay in edit mode (resume_after_restore: the rebuilt node is picked up again).
- Toolbar (CanvasLayer, top centre): 1 Height (Shift lowers, Ctrl flattens to the stroke's start height), 2 Smooth,
  3 Paint (layer + its material + tile; Shift erases to base), 4 Fill (click = flood fill of the touching cells with
  the same layer; Fill by slope lo-hi deg), 5 Holes (Shift fills back; holes show red while the tool is on). Size (m,
  [ ] keys), Strength, Falloff (inner ring = hard core), Pen checkboxes for size / strength (pressure only once a pen
  reports 0<p<1, so a mouse is full strength). One undo step per stroke. Brush rings follow the ground.
- Data: weights terrain/<id>.w8 (4 B per point, layers 1-4; base = rest), holes terrain/<id>.hole (1 B per cell);
  project "layers" [{material, tile}]. Each cell = its strongest layer over its 4 corners (ties: lower), editor shader
  and lp2terrain.cell_layers alike; export: one part per layer's cells, holes left out (no ground / collision).
  Layers without a material = blockout grid in LAYER_COLOURS / BLOCKOUT_COLOURS (terrain_blockout_<k>).
- Editor internals: 32x32-cell chunk meshes (strokes rebuild only theirs), shader with 5 layer samplers + an R8 cell
  layer map (255 = hole), own ray-heightfield march (ray_ground) for the brush, pick shape rebuilt at stroke end.
  Packed arrays are shared by reference: _detach() copies a terrain's grids after each undo push before in-place edits.
- Tested (--terrain-test): edit lock, height / smooth / paint / slope fill / holes strokes via the input path, undo of
  a holes stroke, save of .w8 / .hole; export: 2 layers -> 2 materials, holes out of ground + collision + physics.
- Known: textures are projected straight down (cliffs stretch); a single raised point ties its cells (base wins);
  pen pressure untested with a real tablet; View collision / bake preview still don't show terrain.
- Next candidates: triplanar UVs for cliffs (export too), baked smooth-blend export mode, ground types per layer
  (needs the collision flag decode), terrain in View collision.
- 2026-10-31 later: Holes tool "Brush: Cut holes / Add ground" (Shift swaps). Add ground past the edge grows the grid
  (_grow_to: to the brush + 4 spare cells, MAX_CELLS cap), new cells start as holes, new points carry the edge's
  height + paint, so painted shapes join the edge; off-grid brush point = the ray on the nearest edge's level
  (_brush_point). Tested: +x stroke 40 -> 49 cells, only brushed cells ground, undo restores. _bounds y range cached
  (node meta y_range; update_marker clears, height strokes widen, stroke end clears).
