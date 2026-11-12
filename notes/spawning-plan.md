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
