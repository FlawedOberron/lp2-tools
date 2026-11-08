# Game mode scripting plan (2026-11-08)

User's asks: a visual scripting UI for game modes, probably inside the level editor (so the custom objects modes need
can be made there: carryables, area tags...), modes exported as their own thing. A mode lists "required zones / tags";
maps list what they include; a lobby map missing them shows "Invalid Map" and won't start (host swaps the map in Lobby
Settings). Graph parts: a Settings list, a World Update tick, events Start, On Kill and the rest.

## What already exists (build on it, don't start again)
- Editor: ~/Projects/lp2-editor/scripts.gd, a GraphEdit window (K) for map scripts: events/flow/data/actions, variables
  (numbers, players, lists, markers, vectors), saved in the project as "scripts" {nodes, links}; lp2mapc compiles into
  map.json "script". Objects get a script name (inspector "insp_tag", object_tag) and marker volumes are found by name
  or wildcard: these are the map's tags/zones already.
- Runtime: xlive src/mods/scripts.cpp interprets the graph during the match (pulses, kSteps loop cut, variables, host
  runs it, each PC reports its own character's volume events/health and applies actions on itself).
- Lives core: src/mods/lives.cpp (per-slot state, spectate choice, overlay text) + overlay ui.cpp (UiAddLayer).

## Design
- A mode is its own file: `<name>.lp2mode` (JSON) = {format, name, description, base (stock rules it starts from:
  team / FFA, kills or gauge), settings: [...], requires: {tags: [...], zones: [...]}, script: {nodes, links}}.
  Shared with others like map packages (packages.cpp can carry them later).
- Editor: scripts.gd becomes the graph engine for two document kinds. Map scripts stay as they are. A "Game Mode"
  document (File > New Game Mode / Open) uses the same window with the mode node set added, plus side panels:
  Settings list (rows: name, kind number/choice/on-off, default, range/choices; these become lobby rows on our
  overlay settings panel and graph variables) and Requirements (tag/zone names, each with "at least N").
- Maps: lp2mapc writes the map's tag/zone names (object script names, marker volume names) into map.json "provides".
- Lobby: the host's mode + map are checked (requires vs provides). Missing -> "Invalid Map: needs <tag>" on our
  overlay lobby panel, Start blocked, map swap offered.
- Runtime: scripts.cpp runs mode graphs as a second graph next to the map's, with mode events/actions wired to
  lives.cpp. Host-authoritative as now.

## Mode nodes (new)
Events: Match start, Round start, Round end, World update (every tick, with dt), On kill (killer, victim, weapon kind),
On death (victim, cause), Player joined / left, Player spawned, Timer (exists), Volume entered (exists),
Carryable picked up / dropped / delivered (later, needs carryables).
Actions (lives core): Spawn player (at marker / random marker from list), Hold player (no body, not out), Eliminate,
Respawn rules (respawn delay, lives), Queue: push / pop / move / list, Spectate (player -> target), Score: add / set
(player or team), Round: end round (winner), End match (winner), Show text (all / player / team; banner, HUD line,
counter at the top), Set team.
Data: Players (all / alive / team / queue), Count, Team of, Score of, Lives left, Setting value, Leader.

## Arena example (first test)
Match start -> Queue all players (random order) -> Pop 2 -> Spawn each at markers "arena_spawn_*".
On death (victim) -> Eliminate victim -> Queue push victim (back of the line) -> Pop 1 -> Spawn at the free arena marker.
Show text: the queue list on the HUD. No tags required (just 2+ markers named arena_spawn_*: requires zones {arena_spawn: 2}).

## Order
1. Runtime first, so graphs can be tried: lives.cpp actions (spawn at a point needs RE of where FUN_008fb130 picks the
   start position; hold without a body from match start), mode events from rules.cpp hooks (kills: the battle message
   data has killer/victim; round start/end exist).
2. .lp2mode loader in the DLL + one hand-written Arena file to test with.
3. Editor document kind + mode node set + Settings/Requirements panels.
4. map.json "provides" from lp2mapc, the lobby check and Invalid Map on the overlay lobby panel.

## Requirement scan (user, 2026-11-08)
- Editor: "Scan game mode" on a .lp2mode (or the open mode document) lists the elements it needs, with counts: markers and volumes
  for now (later carryables, other tagged objects). Built by walking the graph: every node that names a marker/volume (exact name or
  wildcard like arena_spawn_*), with the count it needs (a "random marker from list" / "pop 2 and spawn" needs N matches; a single
  reference needs 1). Output e.g. "Markers: arena_spawn_* x2 · Volumes: capture_zone x1".
- The scan result is what goes into the mode's "requires" (generated, editable to raise counts), so authors don't type it by hand.
- Against the open map: the same list with what the map has (found / missing per entry), so a map can be made to fit a mode.

## 2026-11-08 built (untested in game)
- Editor: modes.gd (extends scripts.gd; J / "Game Mode (J)"): File New/Open/Save(As) to <game>/Modes/*.lp2mode; Name/About/Base;
  Settings rows; Requirements + Scan graph + Check against map; mode node set (MODE_TYPES). Font menu reads <game>/ModCache/fonts.txt.
  Test: ./run.sh --project <copy> --screenshot X.png --mode-test (Arena graph, scan, check, save, window shot).
- DLL: rules.cpp RulesHold/RulesRelease/HeldTick (held = character removed + held death view; release = round-start spawn
  (0,0,0) + CharacterTeleport); LifeState::Held; lives.cpp LivesMessage (banner/top/hud) + round banners; LivesTick Arena test
  (arena-test.txt in the game folder = fighters at once; arena_spawn_* markers if the map's script has them); scripts.cpp
  ScriptMarkerFind; ui.cpp ListFonts -> ModCache\fonts.txt, UiFontNamed (loads on first ask, rebuilds the font texture).
- Not yet: the mod running .lp2mode graphs; Show text font/colour in LivesMessage; round banners only on the host.

## 2026-11-08 zone tags + outlines (built, untested in game)
- lp2navmap: zones carry "tags" (zone volume "zone_tags") and "outline" (closed floor loops of the zone's outer edges, cm).
- DLL: packages.cpp NavZone tags/outline; zones.cpp draws each shown zone's outline as a fence (outline extruded up, fading,
  bright floor line) on the overlay, projected through the local camera (rules.cpp RulesCamera: uCamera mCameraPos +0x40,
  mCameraUp +0x50, mTargetPos +0x60, mFov +0x30, read as degrees; logs the camera every 30 s to check). Script node
  "zoneoutline" (show / hide; Zone / tag pattern, colour, height cm, seconds 0 = until hidden), host runs it, the shown set
  rides the script state message (sent on change + every 2 s) so clients and late joiners see it.
- Editor: node in map scripts and modes; mode scan lists it under "Bot zones (name or tag)"; Check against map reads
  .preview/navzones.json (names + tags; needs Build Navmesh first).
- Unverified: projection handedness (right = forward x up assumed) and fov being vertical; if the fence is mirrored or
  scaled wrong, that's where.

## Decisions (user, 2026-11-08)
- HUD replacement (crosshair, weapon / ammo panel, radar, health / T-ENG...) is for control, so it is essential only in
  custom modes: a mode replaces the stock elements it wants (hide the stock one: Flash clip / native draw; read the
  data; draw ours on the overlay), stock modes and the campaign keep the stock HUD. Suggested order: radar (blips
  decoded in radar.cpp), weapon / ammo, health / T-ENG, crosshair last (per-weapon, spread, lock-on, scopes; VS
  cockpit stays stock at first).
- Our modified Survival (rules.cpp lives / rounds on the stock modes) should become a custom mode later: a .lp2mode
  using a few menu variables (Settings rows), e.g. Lives, built on the lives core. Needs the mod runtime for
  .lp2mode graphs first.

## 2026-11-08 mode runtime v1 (built, untested in game)
- Survival on the stock rules is off (rules.cpp g_survival = false; the lobby row is ignored, logged once). Its round 2+
  respawn bug: it counted the game's per-player deaths, which our rounds don't reset. Spectate broke the same way.
- Runtime: scripts.cpp runs <game>\Modes\<name>.lp2mode "compiled" (lp2mode.py; the editor compiles on save) as a second
  graph on the host (offline: here), from HudUpdate (ModeFrame). mode.txt in the game folder: the mode's name, then
  "setting = value" lines. Events: matchstart, roundstart, roundend, worldupdate, ondeath / onspawn (lives.cpp state
  changes), onkill (never fires yet: killer unknown). Actions: spawnplayer (release at a marker), holdplayer, eliminate
  (rules.cpp g_elimMask, shown as Out), respawnrules (lives per round / manual), queue, playerinfo (team, deaths, lives),
  teamlist, endround / endmatch (EndCheck + ranking bonus; rounds' "over"), showtext. score does nothing yet;
  onjoin / zoneenter not run (left out by the compiler). Holds, eliminations, releases, texts go to players as kMode
  messages (+ masks every 2 s).
- Team game flag: lobby rule byte (slots +0x74 >= 1), training screen rule; round banners / spectate use it.
- Modes in lp2-tools/modes: Survival (team: a team with nobody standing loses the round), Survival FFA (last one wins).
- Only versus matches load a mode (RoundTime). Clients: holds of their own player come from the host's messages.

## 2026-11-08 score vs points (built, untested in game)
- RE (DX11 FUN_0100d360, the match-end career points): each player's points come from their own game score
  (DAT_01852238 +0x103c[slot], kills etc.) x a per-type factor, plus a placement bonus (DAT_0182f5cc[rank + n*16],
  elimination types) and win / draw extras. The ranking list (flow +0x74) only gives ranks (0xabc team / 0xacc slot; ties
  equal via FUN_010072e0); its score values are never read. So the game already keeps points and placement apart.
- With a mode running, rules.cpp ModeRanking orders by: rounds won (no rounds: the round's End winner), the mode's score
  (Score node: add / set, player or team; match + round totals in scripts.cpp; team = its own + its players'), still
  standing / out last (RulesEliminate records the order), then the game's points. The list's value is a tier (ties stay
  ties); g_roundScore gets the round's tier (RoundEnd's winner). Game points are never touched -> top killer still earns.
- playerinfo "score" = the mode score. Not yet: "kills" / game points in playerinfo (needs 0x103c per build), a mode
  "award points" node (writing the game score would change career points).

## 2026-11-08 mode -> map events (built, untested in game)
- Mode action "modeevent" (Fire map event: text = name, player) runs the map script's "onmodeevent" nodes (On mode event)
  with that name, case ignored, setting their player variable (scripts.cpp MapModeEvent; host). Maps without one ignore it.
