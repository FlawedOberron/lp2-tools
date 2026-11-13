# Spawning options (2026-11-12)

User's spec (2026-11-12): a Spawning option per game mode; instant picks (Random / Safe / Unsafe); team games also
Near Allies, Zones: Set, Zones: Dynamic (editor volumes); Data Posts option (Default / Add Nearby Points / Ignored);
Spawn Distance from where you died (Any / Near / Medium / Far). Sub-options hidden while Spawning is Default.

## Built (installed 2026-11-12, NOT tested in game, nothing committed)
- Menu: Game Options > Spawning > page (rules.cpp kSetupSpawning): Spawning, Spawn Area (team games), Spawn Distance,
  Data Posts. Lobby panel section "Spawning", same hiding. Extras keys spawning / spawnArea / spawnDistance / spawnPosts
  (indexes 30-33), rule string spawn= / sarea= / sdist= / spost=, saved in profiles (gamerules.cpp kExtraRules).
- Runtime: xlive src/mods/respawn.cpp (comment at the top has the RE). Instant picks: state 2 -> held in the death view
  for the dialog's countdown length -> state 4 (pick handshake) with +0x64 cleared -> game spawns -> CharacterTeleport to
  our point once state >= 6. Only for slots this PC runs (own player; host: bots). Off while a game mode script runs.
- Points: the loaded rInitPosSet (FFA: kinds 0 + 3; teams: own kind 1/2, matched to the slot's base entry), team games
  also the map's KojinBattle set of the same variant, fetched via sResource vf11 (find, else load) at the first respawn.
  Whole Map in team games = own team points + FFA points (user can ask for team points only).
- Data posts: the respawn table's owned entries (game +0xd6c / +0xd80 / +0xe80). Add Nearby Points: points within 20 m.
- Safe / Unsafe: enemies (distance falloff), deaths within 20 m in the last 15 s (team games: allies'), spawns there in
  the last 8 s (avoided both ways); weighted among the best 3. Never within 12 m of a living enemy while another exists.
  No line of sight (no usable ray function found yet). Distance: nearest / middle / farthest third from the death spot.
- Zones: map.json "spawn_volumes" [{min, max, yaw, team 0/1/-1, order}] (packages.cpp). Editor: volume effect "Spawn zone"
  (lp2-editor volumes.gd: Owner, Order), lp2mapc.py exports it. Dynamic: a zone flips to a team holding it alone 10 s,
  if next (by order) to a zone it owns, never a team's last; each PC works it out locally (not synced; only its own
  players' spawns use it), "Spawn zone captured / lost" top line. Stock maps have no zones: falls back to Whole Map.
- Setup menu: short pages filled with hidden blank rows so Begin Match sits in the bottom slot; 4 px dividers under Back
  and over Begin Match (flash/setup.as lp2SetupDividers, setup.h recompiled vs lp2-assets/.tmp/id221/id221.gfx).

## Test list
1. Setup menu: Begin Match at the panel bottom on short pages (Anchor, Spawning), dividers placed right, mouse/keys skip
   the blank rows.
2. FFA Bot Match, Instant: Random: no respawn dialog, death view lasts about as long as before, log
   "mods: respawn: player N -> free-for-all point at ...". Facing right (Dir from the record, degrees)?
3. Team match: log "N free-for-all points from tool\InitPos\Online\...-KojinBattle-NN (resident|loaded)" - or "not found".
4. Safe vs Unsafe feel; Near Allies; Data Posts in a Data Post Battle (owned post spawns).
5. Editor map with Spawn zones (Set, then Dynamic): log "spawn zone N -> team T".
6. Online: a client's own respawns (each PC picks its own); check the other PCs see the character at the new point.

## Open
- LOS for threat; zone fences on the overlay; syncing dynamic zones from the host; respawn delay setting.

## 2026-11-13 test (DX9, Guardian, team bot match)
- Random: good. But the spawn-point menu still showed: it isn't the state 3 countdown, it's the second half of state 1
  (the cockpit shows it while +0x100 <= 0 < +0xfc). Fixed (installed, untested): RespawnAfter, right after the
  controller's update, goes 1 -> 4 as soon as the death camera's timer (+0x100) is done, clearing both timers; the old
  hold of the countdown's length in the death view is gone.
- Radar team colours never drew: the blip add (FUN_00ed8aa0) returns a pointer, not the entry index, so no side was ever
  stored (no "blip kind" line in any log). Add now takes the index from the buffer count. Untested; look for
  "radar: blip kind N for own team".
- Bot stalls: stall map added (bots.cpp IdleTrack): every 60 s "bots: stall map" + worst 5 m cells with positions,
  stalled-on-a-path vs no-path seconds.

## 2026-11-13 second run (DX9, Guardian team bot match)
- Instant spawn: user says good.
- Radar: sides now recorded ("blip kind 5"), but colours were ARGB guesses; the draw (FUN_00ed8fb0) uses ABGR
  (enemy codes 0xff4040ff red, code 0x21 0xffff8060 blue). Now own 0xffff8060 / enemy 0xff4040ff. Untested.
- Bot aim: AimHeight (bots.cpp) lowers the game's aim point to 0.62 of its height above the target's feet unless a
  head spell is rolled every ~1.5-2.5 s (easy 5 %, normal 15 %, hard 35 %, veteran 60 %); soldiers only. Aim log line
  now gives the game's point height ("N cm above the feet") to check the 0.62. Untested.
- Bot stalls: stall map's worst cells = spawn points on small navmesh islands (Guardian List_guarde97: 1437 polys in
  14 link components: 1047, 217, 45, 38, 27, 23, ...). Routing is per bot zone (ZoneWaypoint), so a zone spanning an
  island and the floor gives "same zone: run at the goal" and the game's path search finds nothing. Jump/grapple
  presses are only logged with bot-log.txt (not checked). User: nearly all of Guardian is reachable on foot, so the
  islands are navgen splits (AGENT climb 55 cm, slope 50, radius 40) -> editor: colour islands + weld edges (asked).
- Quick Resupply with 0 grenades, other grenade type: needs the slot swap. FUN_009d21e0 (DX11) thiscall(fighter,
  weapon, slot) puts a weapon in a slot (+0x1688 + slot*4), callers incl. the spawn FUN_008fb130; old grenade must be
  dropped/hidden too. Not built.

## 2026-11-13 navmesh pieces + welds (editor), grenade swap (all uncommitted, untested in game)
- lp2navgen: pieces(), auto_welds (open edges of different pieces within "weld" cm across, <= climb up, clear line
  60 cm up through the collision), manual_welds (project "nav_welds" [{a, b}] cm), weld_links (LNV links both ways,
  cost centre distance + 50); generate(agent=) for project "nav_settings" {climb, slope, radius, weld}.
  lp2navmap: welds join regions (playable area) and zones (walk links); navmesh.bin + piece u16 per tri + welds.
  lp2mapc NAV_INPUTS + nav_settings / nav_welds (stamp).
- Guardian (copy in scratch): 47 pieces (largest 419 of 1437) -> weld 100 cm: 300 welds (6 blocked by walls),
  18 pieces, largest 1286; zones 75 -> 46.
- Editor navmesh.gd: Colour by Radar floor / Piece, Generation settings, Add weld (two clicks; right click cancels),
  weld lines (white auto, yellow hand, orange unbuilt). Godot --check-only clean; not run in the GUI.
- resupply.cpp GrenadeSwap: empty grenade slot + another kind underfoot -> game equip FUN_009d3f80 (DX9 0x9c45c0,
  DX11 1.1 0x9d3ee0, DX9 1.1 0x9c4340), the dropped empty one hidden. Log "resupply: grenades: took ...".
  Each PC swaps locally (puppets too); a remote PC's view of a puppet's grenade count may differ (online untested).
- Navmesh hand edits (same day): project "nav_removed" / "nav_added" [{brush: [[x,y,z]...], r} | {piece: [x,y,z]}]
  (lp2navmap.marked: brushes, then pieces over shared edges only, never welds: a weld-joined piece removed the whole
  main floor in the first test). Added back first (overrides markers / kill floor / kill / limits), then removed.
  Editor: Action Take out / Add back, Piece / Brush tools, grey / blue preview, list with Show / Undo. Guardian copy:
  removed 21, added back 22 as expected. GUI not run.
- ROOT CAUSE of the split navmesh (2026-11-13): lp2navgen.snap_corners snapped each triangle's corners on its own and
  re-joined copies only at the same spot to 5 mm, so stairs / ramps (copies 40-70 cm apart) split. Recast itself has
  Guardian's main piece at 1286 polys; after the old snap 419 / 194 / 184 / 168 / 153. Now copies within 1.5 x climb
  stay one vertex (median height): Guardian playable area 47 pieces -> 19 (largest 1284 of 1435), no welds.
- Asked next (user): navmesh hand editing - verts as handles, drag vert onto vert to weld, show edges, drag edge onto
  edge to weld (closest ends), right click to remove; a small tool bar in the Navmesh window; export / import the
  navmesh as a file (grapple / drop / jump marking later; "wall mesh" later?). Also: bots aware when fired at (not
  only hit), reaction scaled by angle and by difficulty.

### 2026-11-13 (later): n-gon navmesh editing + bots react to being shot at
- Editor: Navmesh window toolbar (navedit.gd): Hand edit freezes the built navmesh (navmesh.bin, all triangles) into
  assets/nav/edited.obj (project.json "nav_mesh"); lp2navmap.read_obj uses it instead of lp2navgen.generate (welds, marks,
  playable area, zones as before); "nav_mesh" is in lp2mapc NAV_INPUTS. Select (click / Shift / box), vertex drag-merge,
  Enter = n-gon (outline loops, holes bridged, Geometry2D triangulate, winding kept), add corner on outline (splits the
  outside triangle), Delete free corners, Esc cancel, Ctrl+Z. Export / Import OBJ, Regenerate (drops "nav_mesh", rebuilds).
  Tested headless (merge, hole, split, OBJ round trip) and Guardian frozen build = generated build (1435 polys, 19 pieces).
  Not tried in the GUI by me.
- Bots (installed, untested): radar Shot records the shooter's facing (world matrix Z row +0xc0; first shot logs it against
  the quaternion at +0x40 to confirm). bots FiredAt: a shot in the last 600 ms facing the bot within 2.5 m + 7% of distance,
  up to 60 m, 6 m up/down -> pending reaction if it has no target or the shooter is < 0.8x its target's distance.
  ReactionDelay = (kReaction + kMissExtra for misses) x (1 + kAngleCost x off-facing/180, half for hits) x 0.85-1.15.
  TargetAttacker now inserts a shooter missing from the grudge table (FUN_0090ffb0 targets the top value).
  Log: "bots: slot N shot at / hit (X deg off its facing)".

### 2026-11-13: career points from bot matches (installed, untested)
- Why none: match-end results DX11 FUN_0100b6b0 (DX9 0xffb2d0, 1.1 0x100b9a0 / 0xffb5e0) adds the match points to the
  career total (DAT_01852238 +0x5060[FUN_0081fd80(-1)], 3 ints) and the per-mode rank stats (+0x7ee0 records,
  leaderboards) only when session +0xcc64 == 1 (not System Link) and +0x1136db == 1. Bot matches are System Link.
- User chose "career points only". career.cpp hooks it: non-online + a bot slot (slots +0x1b1) + results +0x138 == 3 ->
  after the original, the game's final points (game +0x817c, boosts applied; sentinel shows whether it was set) go on
  +0x5060[mode]. Rank stats untouched. Log: "career: bot match: +N career points (mode M: a -> b)".

### 2026-11-13: radar team colours, real cause
- Log: "blip kind 5 for own team". FUN_00edd730 maps add kinds 1-2 -> code 5, 3-4 -> 6, 5-6 -> 9, 7-8 -> 10, 9 -> 8 (flag 4:
  7 / 0xb); FUN_00ed8fb0 draws 5-7 green, 8-0xb red. In bot matches the game adds teammates as kind 5 (red markers), and
  MarkSides / Draw only handled kinds 1-4 / codes 5-7, so nothing was ever recoloured. Now kinds 1-9 / codes 5-0xb.
- Shooter facing confirmed in game: matrix Z row == quaternion forward.
- Grey main navmesh after save: applied piece marks re-matched the neighbouring (main) piece. lp2navmap result now lists
  the applied marks ("marks"); the editor previews only newer ones (navmesh.gd _unbuilt). Needs one Generate per project.
- Stock navmesh rebuild with the snap fix: lp2stocknav.py --work ~/Projects/lp2-build/stocknav-work (14 maps) ->
  src/mods/stockarea.bin + stocknav_data.h, for the next publish.

### 2026-11-13: stock navmesh rebuilt + bot traits (installed, untested)
- lp2stocknav.py rerun with the snap fix (work folder ~/Projects/lp2-build/stocknav-work, ~25 min): stocknav_data.h +
  stockarea.bin regenerated (maps 01/09/10/12 still Capcom's training navmesh). For the next publish.
- bots.cpp per-slot SlotTraits (with the archetype, jittered): social (lone wolf <= 0.35, co-dependent >= 0.6), bold,
  grapple cost factor. Logged on the "is a <archetype>" line.
  - Social (RoamPoint, team games): co-dependents goal = nearest teammate human (x0.6 distance) or co-dependent bot within
    80 m, re-picked every 3 s, no goal within 8 m; lone wolves add up to 60 points to areas within 40 m of teammates.
  - Grapple links: (350 + 0.5 x length) x the bot's grapple factor (was 1500 + length): grappling now competes with walking.
  - Melee: EvalParam modes 16 (own gun empty / reloading) and 17 (bold); lp2brain.py melee(): Strike + bold 600,
    MeleeRush (no shooting, 1.5-15 m, empty 2000 + bold 1200 - 1500 + close 600) and MeleePush (firing, 2.5-12 m,
    bold 1800 + close 400 - 700), each linked to a 3 m strike (pad action 1). brains.h regenerated.

## 2026-11-13: Occasional Interval (Stagger page)
- New rule row "Occasional Interval" (extras key staggerEvery, rules string socc=, own row 34): 0.5 s .. 5 s in 0.5 s steps,
  default 1.5 s (the old fixed kOccasionalMs). Applies to Flinch Occasional and Knock Occasional on every stagger row.
  Setup Stagger page (after Melee Stagger) + lobby list. Built + installed, untested.

## 2026-11-13 later: career points take 2, frame watch
- Bot match test: "career: bot match ended, but the game worked out no points (session flags 0x6a)". The results
  function only computes match points when session flag 0x4 (ranked/player match) is set or game +0x257 == 0; that
  block also adds Fraction points, the matches-played count (+0x506c) and Fraction/match achievements (FUN_007f52c0,
  FUN_0080f500). career.cpp now computes the points itself: slots +0x1154[player] + 100 x round wins (+0x1ad4) when all
  rounds played, times boost factors (FUN_009aa5b0 abilities 0x25-0x29, floats per build). Career total only.
- Frametime spikes reported. ui.cpp FrameWatch (Present hooks): slow frames (>40 ms and >2.5x average) logged with our
  hooks' time that frame (CostScope in bots ThinkBody/Resolve/PathStep, rules HitHandler, radar hooks). Log: "mods: frame:".

## 2026-11-13 user test of test-2026-11-13
- Good: Occasional Interval, Grenade Swap (empty slot), Spawn T-ENG, fewer bot headshots, editor navmesh tools.
- Editor navmesh tools to improve (user): hold Ctrl while dragging a vertex to merge it onto another; clicking a vertex
  handle sometimes passes through and adds a new vertex elsewhere (handle pick must win over the outline click).
- Still to test: ladders (Kraftwerk 02 first, then Helix 08), spawned-without-grenades fix, grenade key lockout.
- 2026-11-13 later test: ladders WORK (bots climb), grenade key unlock WORKS. Career +2339 added, but the Fraction
  (faction) level didn't move: by design so far (career.cpp adds the career total only; Fraction points game +0x509ec
  are in the skipped points block). User asks if it's a DNF issue: no.
- Frame spikes persist (45-60 ms every 3-8 s, also in the lobby after the match): our hooks ~0 ms in them. System:
  Steam background game recording is ON (localconfig BackgroundRecordMode 1, 3.6 GB gamerecordings; journal: clip
  trimming + audio mix all match); plasmashell ~19% of a core (QSGRenderThread + a QFFmpeg decode thread: video
  wallpaper / media widget?); VRAM widget not spamming any more. Suggested: one match with background recording off.
- Decoy grenades (user): bots stare at decoys, even their own / teammates', never shoot them. Wanted: ignore
  friendly decoys; don't switch to a decoy unless the real target is out of sight; smarter bots shoot enemy decoys
  near enemies and move away from nearby ones; dumber bots shoot any decoy they look at. Needs RE: how the game's
  AI targets a decoy (target list / grudge entry for the decoy object, its owner / team), then filter in bots.cpp.
- 2026-11-13 22:17 System Link "Communication Error - Connection Lost" again, bot match (area_online_13), no window
  minimised: the game called XSessionDelete 0.2 s after a respawn; nothing of ours logged before it (the only notify
  was a Steam friend presence change at 22:13). The earlier one was blamed on minimising; maybe not.
  Built (not installed: game running) mods/gamelog.cpp: the game's network library (sNetworkLibraryXbox, DX11
  DAT_018de398, DX9 DAT_018ce2d8, 1.1 0x18df398 / 0x18ce2d8) print methods vtable +0x20 (level, fmt), +0x24 (error),
  +0x28 (warning) are "xor eax,eax; ret" stubs: a copied vtable routes them to our log ("game net ..."; 10 lines/s,
  repeats dropped). Strings to look for: "Upstream disconnected", "no receive timeout", "leaveSession timeouted",
  "setNetworkConnectionEvent ... error", "relay auth error".
- Fraction points from bot matches: career.cpp, built + installed 22:04, untested (log "+N Fraction points").
