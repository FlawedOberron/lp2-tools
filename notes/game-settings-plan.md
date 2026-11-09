# Custom game settings menu (plan, started 2026-11-05)

User's direction: settings grouped into categories, e.g. **Player** (primary, secondary, grenades and ammo, stagger, grapple range), **Gear** (VS on map, weapons on map),
**Game options** (round count, kill count, ...), with more sub-categories where a group gets long. Grapple Speed lives here, as its own row.
Earlier design notes: later-2026-11-03.md "Plan: game setup menu" (Halo 3 style flow, saved modes, random playlists).

## Why a new menu
The game's Settings pages are full (rules row table 10/10) and they differ per game type. Ours has no row limit.

## Layout (user, 2026-11-06)
One Game menu, top end settings first, then sub-menus:
1. **Map**, at the very top. Map and game mode are separate things and people will want to switch maps.
2. **Game Type**, then the **time limit** and **score limit** (or that type's equivalent: kills, points, gauge).
3. Sub-menus: **General**, **Rounds**, **Player**, **Weapons**, **VS**, more as needed (**Bots**).

Contents so far (S = stock rule today, M = our mod rule today, N = new; S names to confirm against id221):
- **General**: Max Players S, Private S, Respawn S, Start Number S, Weather S, Friendly Fire S, Referee S, Penalty / Kick S, Team Change S, Survival M, Lives M
- **Rounds**: Rounds N, replacing the stock Halftime row (below)
- **Player**: Default Weapons S, Secondary M, Grenade type S, Grenade count N, Ammo Supply M, Infinite Ammo M, Infinite Grenades M, Hit Stagger M, Harmonizer M, Grappling Range M, Grapple Speed N, Customize / Ability S. Ideas: Health, Damage, Regeneration.
- **Weapons**: Weapons on Map N (requests-mp-menu.md), Set Weapon S, Set Grenade S. Idea: pickup respawn time.
- **VS**: VS on Map S (Set VS). Ideas: VS Health, VS respawn time.
- **Bots**: Fill / count, Difficulty, Brain, Personality, Taunts, Loadout

## Rounds (replaces Halftime, user 2026-11-06)
Stock Halftime (game text: "you will switch start points with the opponent halfway through the match"): on = the rule byte at slots object +0x84, time limit halved (DX11 FUN_01006fe0), second half flag +0x1f44 set by FUN_010068e0, handled in cNetGameManager::vf6 / FUN_01009b90, also read by FUN_0100d360 (scoring, divides by 2 when on) and FUN_0085c540 (slot handling).
The user recalls the map resetting at half time; NOT confirmed from the code yet. That reset, if real, is the basis for rounds, as the game already has a mid-match restart that keeps scores and works online.
Modes wanted: fixed count (3 rounds, all played) and best of N / first to X (ends early: needs a behaviour change, the stock flow knows exactly one break). Whether sides swap each round could be its own row.
RE: read FUN_010068e0, vf6 state 8 and FUN_01009b90; find how the second half starts; can the first-half flag be re-armed for more breaks; how score carries over; check clients follow it (cNetRule).

## How it plugs in (rebuilt 2026-11-06, not yet seen in game; replaces the Sections tabs)
The stock screen stays as the shell: map circle, ten rows, its stepping, its start flow. Render from id221: left disc + right rows, which is already the approved layout.
- rules.cpp "Setup": FUN_00e90180 detoured as CreateTick. First tick forces the slot list's confirm, so state 1 with slot 0 and tab 1 is the only view; back from the top page leaves through the state 0 back path.
- Pages: Top (Game Type, Map, Game Options, Create Match) > Options (time, score rows, then sub-menu navs) > Section; Top > Types (Save Current Settings, each type's header, locked Default, its profiles). Scroll past ten rows; LB/RB jumps types.
- Row table page 0 and flash/setup.as lp2SetupRows hold the visible window. Nav rows use offset 0x37 (kNavOffset) and items 520+; left/right never reach the game on them. All input except left/right on value rows is handled by us.
- gamerules.cpp: types, built-in defaults (FUN_008219b0 copy + ours off), ModCache\gamerules\current.json and profiles\*.json (names, only differences from defaults). Map, max players, private, players desired carry across and aren't in profiles.
- 2026-11-06 test round 1 (user): slot list text hidden from the wrapper on updateMember (flash/setup.as lp2SetupLook); wheel flipped; Game Type is now types > entries (Default, profiles), Top > Types > Entries; W (button bit 4, mouse id 1) opens a Save Profile row, typed via a temporary WndProc on the foreground window (WM_CHAR), prefilled with the current profile. Not confirmed yet: DirectInput may swallow WM_CHAR; then Enter saves the prefill/next free number and Backspace cancels after 6 ticks.
- Colour: the grey backdrop isn't in id221 (the frame renders black there) and uCustomCamera presets (FUN_008cbbf0) are only camera positions. First try: a blue fill at depth 0 under mc_main, 30% alpha. Grey tabs and bottom band unchanged. The campaign's real blue is unresearched.
- Bots row: nothing to wire yet. System Link / player matches can't host bots until plan E in bot-match-plan.md (U1-U6) is researched and tested with two accounts.
- First pass limits: Map is a left/right row, not a list. Delete profiles by file. Nav rows have no description. Two blank grey tabs remain (untouched). New rules still need extra storage rows (rule files are ready; virtual rows aren't). Lobby sync still reads the 0x38 bytes.

## Order
1. Row table + panel: Map, Game Type, limits, sub-menus, moving existing rows over (no new behaviour). Test.
2. New rules, cheapest first: Grapple Speed, Grenade count, Weapons on Map.
3. Rounds (needs the RE above).
4. Radar sub-menu: Radar + detection rules + team coloured blips; then personal colours everywhere.
5. Saved modes.
6. Bots page + bot match sharing the table. Then playlists.

## RE still needed
- Stock row names above are from memory of the flash notes, not checked: confirm each against id221 (Rounds and Respawn time especially).
- Grapple Speed: reel speed in uWp00 FUN_00c8a720 and pull in FUN_009cb4f0 (range scaling is in rules.cpp kGrappleLimitAt).
- Weapons on Map: slot -> weapon resolution vs rewriting objset group 4 (requests-mp-menu.md).
- Which stock rows apply per game type: OnlineRule.mainItemArray / sub1 / sub2 [catg][row] in flash\playermatch\id221.
- How the create screen starts the session, for confirm (FUN_00e8bc00 -> state 6, e8c270, e8f260, e90180).

## Decisions for the user
- User 2026-11-06: the four saved slots go. Each base type has a locked **Default** entry above its saved profiles; picking any entry loads exactly what it holds, so switching to another type's Default loads that type's defaults. No per-type memory of unsaved edits.
- User 2026-11-06: proposed layout approved (circle left; Game Type, Map, Game Options, Create Match; description line). Game Type opens a list of all base types, with saved profiles for each type listed under it.
- User 2026-11-06: rip out the create match menu and nearly start again. Keep the left-hand circle with the map thumbnail; organise it more like Halo 3's game setup flow, with the looks staying very LP2. The tabs (Sections) are interim at best. Rule files and flat game types carry over; layout awaits the user's reaction to a proposal.
- Decided 2026-11-06: our own rule storage in JSON/YAML files, with a pre-programmed default ruleset per game type in the DLL. No separate scoring-type rule: flat game types, Elimination-[Score Type], for quicker browsing. Must allow custom game types later (user expects those soon, with weapon skins, possibly next).
- Decided 2026-11-06: layout above; Rounds replaces Halftime.
- Decided 2026-11-06: bot fill targets the stock "No. of Players Desired" row (Settings 3, rules byte [0x15]), which belongs in General next to Max Players.

## Radar (part of this menu, user 2026-11-06; nothing built, no RE done)
Goes in with this menu, as a **Radar** sub-menu. Wording is the user's, can change.

Stock: capturing a data post gives radar over the whole map and shows blips of players / VS near that post. All blips are red.

Two layers, in this order:
1. **Radar** (who is a candidate): Always On / Near Data Post (default, stock) / Hidden.
2. **Detection** (which candidates actually show), separately for **Players** and **VS**:
   - Always Show (default, stock)
   - Show While Moving & Shooting: any movement counts, including crouch moving.
   - Show While Running & Shooting: faster than the max crouch-move pace, or grappling.
   - Show While Shooting

So under Near Data Post only players near a held post are checked against the detection rule.

**Team Coloured Blips**: game option, MP.

**Personal team colours** (Options, local, never synced): your team is always blue and the enemy team is always red by default, with
a menu to pick the colours. Applies everywhere (blips, names, markers, HUD, whatever shows a team colour). No teams: everyone gets
the enemy colour.

Bots: the same two layers decide which enemies a bot "hears": a blip = rough position -> investigate, never a snap-aim
(bot-match-plan.md, Radar under perception). This is what makes data posts worth grabbing to them.

RE needed:
- Where blips are drawn and coloured, and what decides who shows (FUN_00ed8510 draws the radar; setNoise is the static, not blips).
- Post radar: the "near" radius, and how holding a post is checked (team / personal).
- Character speed + crouch-move max pace, grapple state, a "just fired" signal; for VS the same. Must work for remote players from
  data each PC already has; otherwise needs syncing.
- Every place that uses a team colour, for personal colours (likely the biggest search here).

## Status 2026-11-06 (uncommitted, installed, untested in game)
- Top page: Game Mode + Rules rows. Options: Bots page, Radar page (kKindOwn rows, values in rule-file extras: bots*, radar, radarPlayers, radarVs).
- Bots: rules.cpp LobbyInput/LobbyPrompt (+0x5b0 boost), LobbyStart (fill + message 7), LobbyLeave (+0x254, +0x50188). Answers U3/U6 in bot-match-plan.md E. Open: FUN_0089e840 case 9 resets AI count from slots+0x72, may undo ours if it runs for player matches; lobby start limit +0x7c/+0xab; stock maps have no navmesh.
- Radar: radar.cpp. FUN_00f74980 = in range of own team's post, every radar decision goes through it. Hidden = FUN_00edd730 told off. Detection = skip FUN_009bde40 for undetected enemies. Shot = FUN_00c7ce40 (holder weapon+0x2194, DX9 0x2184), remote firing unconfirmed: look for "a shot from another unit". kRunPace 300 is a guess: read "own speed" in the log (crouch-walk, then run) and set it.
- Not done: Team Coloured Blips, personal colours (blip icon code is in FUN_00edd730: bVar20, frame table DAT_01630680).
- Anchor page (own rows, rule-file extras anchorRange 0-12, anchorSpeed 0-11; byte 0x35 row retired): Range Off,1/4,1/2,Default,2X..10X; Speed the same less Off. Speed = launch velocity 120.0, 3 movss sites (kAnchorSpeedAt), return flight untouched. Untested: at the top values one step may pass the range limit before the hit check.
- Fall Stagger (Options row, extra fallStagger): 19 uHuman landing compares of cJump +0x17c8 with -40.0 re-pointed to g_fallThreshold (scales 1, 1.5, 2, off). Anchor Speed and Fall are versus-only.

## Grenade counts (built 2026-11-06, untested)
Rows Grenades at Spawn (Default, 0-10) and Grenade Pickups (Default, 1-10), extras grenadeCount / grenadePickup. Totals are units: count = ceil(total / entry +0x4e). Entries get start, magazine and a 10-grenade cap; other-kind pickups start at the pickup count. Stock logs show 1000 and 350 totals: read cost from 'grenade setup' log lines. Bots follow the same rules.

## Halftime read 2026-11-08 (DX11; for Rounds)
- Confirmed in game: halftime reloads the map (stage, slots, spawns) and keeps team scores (log 09:28:50).
- cNetGameManager::vf6 (0x100e1a0) state 5, match end: FUN_01007110(); then if slots(0x1852850)+0x84 (halftime) and +0x1f44 == 0 (first half): +0x138 = 1, FUN_010068e0 sets +0x1f44 = 1, state 6 (break screen FUN_00f480c0(3)), state 6 returns +0x138 = 1 -> restart. Else FUN_00ff8a50 (end), +0x138 = 3. Non-host branch calls FUN_01009b90(0) first.
- +0x1f44 also picks swapped start points (0089.c ~3197-3881, 007f.c 405, 007d.c 3872, 0087.c 15736).
- Time: FUN_01006fe0 (from FUN_01008490) sets game(0x1852238)+0x738 = minutes x 0x708, halved when +0x84.
- Plan for N rounds: detour FUN_01007110 -> after it, +0x1f44 = more rounds left ? 0 : 1 (so the break repeats), detour FUN_010068e0 -> set +0x1f44 to the next round's side (swap each round or not); time = total / N in FUN_01006fe0. Unknowns: FUN_0100d360 scoring halves with +0x84; clients (does each PC run the same end check, is +0x1f44 synced).

## Rounds built 2026-11-08 (untested in game)
- Extras `rounds` (0-9 = 1-10, 10-13 = Best of 3/5/7/9; default 0 = 1 round) and `switchSides` (0 never, 1-10; default 1); lobby keys rnd=/sw=.
- Setup: Rounds section shows our two rows instead of stock Halftime (0x26); time row labelled "Round Time" (setup.as: stock rows take a label of ours if given).
- rules.cpp: RoundTime (FUN_01006fe0) clears +0x84 around the call (full time per round), sets +0x84 = rounds>1, resets the match unless a break is pending (<180 s). RoundEnd (FUN_01007110) counts the winner (best per-round score delta; survival: lives first; tie = no win), re-ranks on the last round, then +0x1f44 = over. NextRound (FUN_010068e0) sets +0x1f44 = (round / every) & 1. Ranking: wins*1e7 + score.
- Known gaps: kill/point targets count over the whole match (game keeps scores across the break); FUN_0100d360 end bonuses follow +0x1f44 parity; clients unverified.
- Test 2026-11-08 10:03 (Team Survival 1 life, Bo3, switch every 2): round 1 OK (won by team 1). Round 2: game resets deaths/gauge at the reload, but the player's controller stayed in the held death view (state 1); once unheld it counted down + respawned (gauge -100, death +1) -> out again, "respawning in #" + spectate HUD. Fix: RoundEnd notes slots with state != 0 (g_slotState) in g_roundDead; RoundTime (continuing round) opens a 15 s window; ControlUpdate sets those controllers to state 0 (timers 0) once they have a body and aren't out. Log: "rounds: player N back in play". Untested.
- Bots idling after posts (both rounds, not a rounds bug): team/elim/fox RunToGoal (Move tgt 5) arrives at once -> NoTarget 1 s -> repeat; lp2brain roam_goal() retargets it to 20 (egg/post keep 5).
- Test 11:43 (same setup): reset never fired (no "back in play"); round 2 player respawned via the held death view -> Self-Eliminated at 0.3 s. Changed: g_roundStartAt set at RoundEnd (60 s window, no RoundTime dependency); logs "down at the round's end: 0x....", "waits for the new round (state, body, out)", "never came back". Camera: spectate switches now call FUN_008f0810(cam, 0) after follow (snap; ports 0x8e0eb0 / 0x8f0af0 / 0x8e1060). "Respawn In" text while out: source not found yet (not in kSpectateHide clips).

## Team coloured blips: RE 2026-11-08 (DX11, nothing built yet)
- Blips are drawn natively, not by the radar Flash (flash\cockpit\id753_PC only does frame/compass colours per mode + noise).
- Add: FUN_00ed8aa0(radar, kind, flags, ?, pos, ...) from FUN_009bde40 (per unit; radar = viewer+0x6bc) with kind = unit+0xcf8. Entries: radar+0xcd0 + n*0x30 (double buffered 0x32 x 2 via +0x1bac): [0] kind, [2] flags, [3] sub, +0x10 pos.
- FUN_00edd730 turns entries into a draw list at radar+0x1634 (0x1c each, count +0x1c0c): byte code (0x80 = flag 0x10 highlight) + uint sub + floats. kind 1/2 -> code 5, 3/4 -> 6, 5/6 -> 9, 7/8 -> 10, 9 -> 8, 10 -> 0xc, 0xb -> 0xe; flags & 4: 5/6 -> 7, 8-10 -> 0xb...; flags & 8 -> 0x10/0x11. Sorted by DAT_01630680[code].
- Draw: FUN_00ed8fb0 maps code -> sprite + ARGB, then FUN_00ecc050(..., sprite, ..., colour, scale). Codes 5/6/7 = sprites 7/9/10 colour 0xff80ff40 (green); 8-0xf = 0xff4040ff (min scale _DAT_0136b1dc).
- Plan: thread-local "current unit" in the FUN_009bde40 hook (radar.cpp already has it) -> tag the entry (spare flag bit or entry +4 for player kinds) with ally/enemy; detour FUN_00ed8fb0: for tagged player codes call FUN_00ecc050 with our colour (own team blue, enemy red; personal colours later). Check which side kinds 1 vs 2 are first (log unit team vs kind).

## Bot area sweep (built 2026-11-08, untested)
bots.cpp: map start points grouped on a 40 m x/z grid -> areas (goal = point nearest the middle). Per team: swept (bots passed through; 120 s), fight (heard gunfire <= 60 m, 30 s). RoamPoint: fresh fight (metres + 2/s age + chance) else nearest unswept area not targeted by a teammate (+100 m if so); all swept -> reset. Logs: "map split into N areas", "sweeps area N", "heads for fighting in area N". Existing gunfire snap kept.
- Respawn countdown (MsgBattle ids 21/22 "Respawn in <#RespornTime> seconds") shows "Eliminated" while survival-out (RulesBattleMessage).
- 12:15 test: round-2 self-elimination again: our ControlUpdate for the out slot didn't run until 5 s in (death at 0.3 s), so the reset moved into Spawn (flagged slot: state 0, timers 0 right after the round's spawn; log "spawned for the new round, death view cleared").
- Bots: RunToGoal ends in 17 ms for goals ~140 m away (38 m ones run fine) -> Resolve now hands out Waypoint(): the start point within 45 m closest to the goal. Areas now 25 m cells (40 m gave 5 areas on map 13).
- Team colour blips built (radar.cpp Add/MarkSides/Draw/Sprite, rule radarTeam "Team Colours" default On, lobby rteam=); log "radar: blip kind N for own team / an enemy". Colours ARGB guess: own 0xff4c9cff, enemy 0xffff4848.
- 12:23 test: round-2 respawn works (Spawn reset ran for slots 1,2,4,6,7). Open: a round-1 survivor kept its old weapon (MG, low ammo, no grenades) although the round's spawn logged a fresh loadout (secondary 0x0c, grenades 375) -> something swaps the unit's weapons after the spawn; not found (game+0x52a6c / +0x52b64 kept in the 2nd half are flags/stats, 0x501d8 is the customisation loadout).
- Respawn text: g_out lags (survival thread) -> RulesBattleMessage checks deaths directly too.
- Team Survival counters (mc_Kill, left, showed 00/00 with 1 life): now players standing + respawns left over players + starting respawns (CounterValues).
- TODO (user 2026-11-08): lobby "Change Match Settings" still the stock menu: replace with a smaller inline version of our setup menu.

## 2026-11-08 later
- Round 2 "self-eliminated": RemoveBody skipped during g_roundBreak; BattleFormat gives no Eliminated text from the break to 8 s after the reload (g_roundBegan), logs "battle message N between rounds".
- Spectate team: Watchable uses SameTeam (body team byte 0xce2/0xcd2, kept per slot after the body goes; falls back to setup team). Log "spectating player N (teams: setup a/b, body c/d)".
- Survivor loadout: the spawn record game+0x28[slot] (weapon kinds +0x10 x8, ammo shorts +0x64/+0x74, +0xb clear = use kept ammo) carries survivors' weapons (halftime design). RoundLoadout snapshots it at the match's first spawn, restores at later rounds; logs other changed bytes.
- Install: ~/Projects/lp2-tools/install-xlive.sh (allowed in settings).
- Lobby Change Match Settings = uIdBattlePlayerMatch (aBattlePlayerMatch.arc). On hold: user asked about our own overlay UI layer instead of Flash patching.

## Rewrite plan (2026-11-08, user agreed in principle; waiting on "go")
1. Overlay layer (our own UI drawn each frame, DX9 + DX11; mappics.cpp already hooks DX9 Present / DX11 device lock). First use: round counter at the top.
2. lives.cpp: one state per slot (waiting / alive / dead-waiting / spectating / out / between rounds). Game events in, game primitives out
   (Spawn FUN_008fb130, body remove vf 0x30, camera follow + snap). The game keeps syncing spawns and deaths to other PCs. The overlay shows its text
   (no more battle-message swaps). Rounds, Survival and spectate move out of rules.cpp, old paths deleted as each one moves.
3. Lobby inline settings panel on the overlay.
- Mode-agnostic core, so modes are rules over it and visual scripting can drive the same API later:
  events OnMatchStart / OnRoundStart / OnDeath(slot, killer) / OnTimer / OnRoundEnd;
  actions Spawn(slot, point) / Hold(slot) / Eliminate(slot) / Spectate(slot, target) / Queue ops / Score / ShowText / EndRound.
- Arena (user's example, and the first scripting test): e.g. 10 in the lobby, 2 spawned, the rest in a queue list; when one is eliminated the next in line
  spawns at a point we choose. No object tags needed. Needs: players held without a body from the match start (our "out" hold, but not counted as out),
  spawn at a chosen point (RE: where FUN_008fb130 picks the start position, so we can override it), the queue shown on the overlay, and a camera for the waiting players.

## Visual scripting for game modes (user, 2026-11-08)
- Node editor, likely inside the level editor (Godot), so custom objects modes need can be made there: carryables, area tags/zones, etc.
  Game modes export as their own file (separate from maps).
- A mode declares "required zones / required tags". Maps list the zones/tags they include. If the lobby's map lacks a mode's requirements the
  match won't start and the lobby shows "Invalid Map"; the host swaps the map in Lobby Settings. Many modes need none.
- Graph parts asked for: a Settings list (the mode's own lobby rows), a World Update (per tick) entry, and events: Start, On Kill, etc.
  (plus the lives.cpp core's events: match/round start, death, timer, round end; actions: spawn at point, hold, eliminate, spectate, queue, score, text, end round).
- First target: Arena (queue of players, 2 spawned, next spawns at a chosen point on elimination) as it needs no tags.
- Runtime: the DLL runs the exported graph (interpreter over the lives.cpp API); overlay (ui.cpp) shows mode text/HUD.

## 2026-11-08 overlay built (step 1)
- ui.cpp: Dear ImGui v1.91.5 vendored in src/third-party/imgui (DX11 backend patched: D3DCompile loaded at run time). Hooks from a throwaway
  device's vtable once the game window is up: DX9 device Present/Reset, DX11 swapchain Present/ResizeBuffers. Fonts via GDI GetFontData (Arial/Tahoma...).
  UiAddLayer(name, draw(w,h)); UiFont(large). No new DLL imports.
- First layer: rules.cpp RoundCounter (top centre, Rounds on + battle HUD updated in the last 0.5 s): "ROUND n" / "BEST OF n", own wins blue, top other red.
- Logs: "mods: ui: overlay hooked", "drawing on DX9/DX11 at WxH", font lines. Untested in game.

## Hit Stagger: split + increase (user, 2026-11-08)

### Bot match data (2026-11-09 13:47, DX11 Steam, rules.cpp call-chain log, ca7f6d6/7e6e588)
All hits go uHuman::vf71 (0xc6b520) -> uCharacterBase::vf71 (0x9d70a0, call at 0x9d7468) -> FUN_00ff7380 (call at
0xff7431) -> vf151 (0x9d4210) -> pools (shrink call at 0x9d63f4, blown 0x9d65ae, third 0x9d65d8). What sits between
tells the kinds apart (return addresses, DX11 Steam):
| kind (user's match) | path marker | points per hit |
|---|---|---|
| bullets (bots' rifles) | none extra (ff7431 straight from 9d7468) / 0x1000329 (FUN_00ffff90) / 0x83649b (FUN_00836440) | shrink -65 + blown -10 (another gun -54 / -8) |
| small ticks (pellets / fragments / fire?) | 0xfa51e1 (FUN_00fa4d70) | shrink or blown -10 / -7 |
| melee (user, early) | 0x8472a7 (FUN_00847270) <- uCharacterBase::vf70 0x9d284a | shrink -800: always staggers |
| anchor (user, later) | 0x834650 (FUN_008345c0) <- FUN_00834890 <- FUN_00c890e0 <- uWp00::vf70; also via 0x832e08 (FUN_00832dd0) | shrink -300 + blown -200 |
| big knock (explosion?) | third pool straight from vf151 (0x9d65d8) | third -1000: staggered |
Unconfirmed: grenades (user didn't do them deliberately; the third -1000 at 13:48:00 is the likely one), which of
the bullet paths is which weapon. Plan: a thread-local hit kind set by hooks on the marker functions (melee
FUN_00847270, anchor FUN_008345c0 / FUN_00832dd0, ticks FUN_00fa4d70; default bullet; third pool = explosion),
read in StaggerAdd to pick the per-kind scale (0 off .. 3x, "flying" for anchor = the blown pool's knock); per-build
addresses via sigport.py for DX9 / 1.1.
- Report: Reduced / Low / Off did nothing against assault rifle fire. The hook only scaled the shrink pool
  (FUN_009b72a0). uCharacterBase::vf151 (DX11 0x9d4210, uHuman::vf151 just calls it) takes points from three pools:
  shrink (+0xc/+0xe, fail sets d7c 0x10), blown (+0x12/+0x14, FUN_009b7350, d7c 0x20), third (+0x18/+0x1a,
  FUN_009b7400, fail -> FUN_009b8bb0: d7c2 0x1000 + vtable 0x528). Now all three are scaled, log line
  "hit stagger: <pool> points ran out" says which one a rifle hit depletes (built 2026-11-08, untested).
- Want: separate rows for anchor / bullet / explosion / melee stagger, each also with increase options
  (e.g. an anchor hit sends players flying = force the blown pool / a launch, not just a stumble). Needs: the hit's
  attack type from the hit param (iVar29 in vf151, cHitParam) to pick the scale; "increase" = scale > 1 on the
  pools, and for "flying" a forced blown reaction.

## Lobby Match Settings, phase 1 (built 2026-11-09, untested)
- rules.cpp LobbyPanel*: overlay panel in the player-match lobby, host only. F1 or the Save Profile button (bit 4) opens it; while open, LobbyInput / LobbyPrompt run with the input zeroed.
- Rows: our rules only (Rounds, Player, Stagger, Weapons, Anchor, Radar, Bots): extras + the g_menu rows. They reach clients via the usual member-data rules. On close: current.json re-saved (file's stock bytes, our rows over them); the next create screen takes the g_menu rows (g_lobbyCarry in PushRules).
- Not yet: the game's own rules (time, score, mode, map). Game Options (uIdBattlePlayerMatch) is only the map list (+0x3b8..0x3c8, FUN_01004490 / FUN_01004510 session update). Phase 2 RE: where a client gets the host's 0x38 rule bytes, and whether they can change after the join.
- Log: "lobby settings: opened / closed / <row> <value> / buttons %08x pressed".

## Lobby Match Settings, phase 2: the game's own rules + map (built 2026-11-09, untested)
- Lobby rule block = match setup (0x1852850 DX11) +0x5e, 0x38 bytes, the create screen's layout (rule +0x74, map +0x79). Every machine has one.
- Panel edits a copy; on close: g_menu rows written in, derived bytes via the game's push (FUN_00e8c270, = kRulesVas.pushRules, ret 4; called through g_pushRulesOriginal), copied into the block, current.json, carried to the next Create Match (whole block, PushRules).
- Sync is ours: host publishes the block hex as member data "srules" (LobbyPanelTick, on change); clients write it into their block from the lobby tick. Stock path exists too (MsgOnline 322-326 "rules changed by the host") but wasn't needed.
- Rows: score rows + kSections rows the mode's row table has (StockRow), labels MsgOnline 38+item (RuleItem), values by item (StockRangeOf; remaps: FF {1,2,0}, grenade {6,0..5}, Battle Series value-2). Not here: mode, max players, private, halftime.
- Map row: stock maps the host has (MapAvailable, VS flag) + own packages as slot 13 (MapsLobbyChoices); package picked only on close (PackagesPickIndex), so scrolling doesn't trigger downloads.
- Open: F1 only. Pad Y (button bit 4) is the lobby's gamer card (FUN_00e969f0 uVar3 & 4); a pad button still to pick.
- Untested: whether the lobby's info panel refreshes, whether the game resends its own block at match start (either way the same bytes), session browser still shows the create-time properties.
- TODO (user 2026-11-09): Random map choices (16-19, Random Small/Medium/Large/All) only pick stock maps. Decide how custom maps join random: the host would pick the map itself (from stock + own packages, by size) before the start, bind it to slot 13 and publish so clients download, and the start waits (content hold). Needs the random pick's writer (map byte rewritten at match start, see history 2026-10-16) replaced or pre-empted.
- Stagger fix 2026-11-09 (test showed Off bullets still flinch, forced anchor reaction did nothing): vf151 counts a reaction level from the pools' answers (shrink out =1, blown +1, third +1 then FUN_009b8bb0 knockdown, only the handler calls it); level -> FUN_009d2860 local camera shake/rumble + FUN_009b9190 meter. Forced reactions now call the knockdown themselves and answer "out" up to the target; Off / Occasional-waiting skip the shake too (HitShake hook). If rifle hits still flinch on Off, the per-shot flinch is an animation outside the pools: next look in vf151 before 0x9d61de and uHuman::vf71.
- Survival sub-type removed from the type list and the sub stepper (it's a game mode now). Setup Flash: ">" rows' labels run to the ">", long values grow left (setup.as lp2SetupFit).
