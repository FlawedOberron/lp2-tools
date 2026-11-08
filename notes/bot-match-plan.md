# Bot Match (System Link) + bot behaviour plan (started 2026-11-01)

User request: a "Bot Match" entry under System Link with total control of a bot match, and bot behaviour
improvements: weapon-aware logic and VS piloting.

## A. Bot Match entry

UX: System Link -> Create Match / Find Match / **Bot Match**. Bot Match opens the create-match screen in
bot mode: every stock rule row plus our rows (Survival, Infinite, ...), plus bot rows:
- Bots: 0-15. Teams: auto / bots vs humans / a custom split.
- Difficulty: an AI param preset. Brain: Stock / Improved (see C).
- Bot loadout: map pickups / random / a fixed weapon. VS: off / on / aggressive.

Engine route (offline, this PC runs the bots, as training does now):
1. Start the training bot-match area for the chosen map. That area already has bots, a navmesh and
   `g_offline`.
2. Overwrite the training's fixed rules with the screen's values in the setup struct (DX9 0x18427b0: kind
   +0x28, ...). rules.cpp already does this for Survival.
3. Bot count already works (Bots row, b1f016c: the mode-start loop and players+0x254 / +0x50188).

Maps:
- The stock bot maps (aArea_TUTOREAL_51..75: ONLINE_12, 10, 01, 09) come first.
- Then any map package with a generated navmesh (lp2navgen.py) + a cloned bot area (section D).

Humans joining a bot match needs networked AI: later.

RE steps:
1. The System Link menu's Flash + handler (where Create Match is picked). Add the entry the way
   netmenu.cpp adds the Options > Network one.
2. The AI Enemy Battle start: what it calls with phase / rule / map (records at DX9 7d81f0) to load
   TUTOREAL_NN. We call the same path from our screen.
3. Which setup fields training resets after our write (hook after its setup, like the Survival override).
4. Per-bot team, loadout and VS: rHmGenerator (EquipWeaponInfo), the area's rObjSet, players+0x254.

## B. How bots think (all data, editable)

Three files, `rThinkPlanAI`, each an XFS file (xfs.py reads it; lp2think.py dumps it). Dumps are in notes/bots/.
- `tool\AI\Think\HumanBotBt`: battle bots, in autoArc\uHm6d.arc (79 plan items).
- `HumanBotCp`: campaign partners, in ID_CORE_MULTI.arc.
- `HumanBotAt`: in ID_CORE_PC.arc.

How a plan item works:
- **Filters** (cAIPlanFilter*): all must pass.
- **Evaluations** (cAIPlanEvaluate*): summed weights; the best item runs.
- **Moves** (cAIPlanMove*): what the item does. Children are in mItemNextIndexArray.
- mRootAttr groups the items: 1 fight, 3 move, 64 riding a VS ("YATTA"), 128 shield, ...

Positions come from `Tool\AI\Pef_Hm40` (XFS, in every area):
- CoverPoint, ShotPoint and LookPoint score positions by danger, visibility (VisibilityHigh / VisibilityLow
  analyzers) and distance.
- ShotPoint's mGoodDist is 1500 cm for every weapon.

Each area's `rIntelligenceBox` (IBL, binary) holds goals / avoid / wait areas.

What stock bots do today:
- **Shooting** (`ShotTaregt`):
  - Allowed between 850 and 3000 cm. Penalised under 1000 (-400), rewarded over 1500 (+300).
  - The same for every weapon: a shotgun bot hangs back at 15 m, a sniper closes in to 15 m.
- **Weapon change** (`WpChange`): weight 30, minus 200 x damage remaining. It ignores distance and the
  weapon type entirely.
- **Grenades** (`ThrowG`): 5-30 m, prefers a height difference.
- **Pickups** (`GetWp`): any weapon within 14 m, weight 1000. No preference for better weapons.
- **FilterWeapon** (mWpMode, mWpAttr / mWpAttr2 64-bit masks) exists, but only the shield items use it.
- **VS** (`RunToYatta` -> `YattaRideOn` -> `YATTA`):
  - Once mounted the bot only shoots for 60 frames, waits for 150 frames, or gets off when the target is
    more than 10 m away.
  - No movement, aiming choice, dashing or VS-specific attacks at all. This is why bots in VS look broken.

## C. Improvements, by tier

Tier 1, data only (rThinkPlanAI / Pef edits, shipped as a Mods overlay of uHm6d.arc):
- **Weapon classes**: copy `ShotTaregt` per weapon class, gated by FilterWeapon masks. Range bands:

  | Weapon class | Range |
  | --- | --- |
  | Shotgun / melee | <= 6 m, push in |
  | Rifles / machine guns | 8-25 m |
  | Snipers / railgun | >= 25 m, favour VisibilityHigh, crouch |
  | Rockets / grenade launchers | 10-30 m, no close range, target VS / groups |

- **WpChange**: switch by range, e.g. to the shotgun when the target is close and to the rifle when far.
- **GetWp**: rank pickups (power weapons, ammo when low) instead of taking the nearest.
- **Grenades**: throw at cover-camping or VS targets; avoid throwing at close range.
- **Difficulty presets**: scale the timers (MoveTime), the ranges and the AIParam weights.

Tier 2, VS piloting (data + likely some code):
- Mounted items under root 64 (Yt-*):
  - Move toward the target or along waypoints (MoveTrace while mounted; check that it drives the VS).
  - Strafe / dash, and fire per VS weapon.
  - Get off when the VS is low on health.
  - Prefer fighting other VS. Pick the VS that fits the job (walker vs turret).
- Needs RE: which pad actions drive a VS (mPadAction ids), VS health / status flags for
  FilterCharStatus, and the turret aim path.

Tier 3, new code (DLL hooks):
- Custom filters / evaluations: weapon class from the weapon table, ammo left, the target's weapon, VS type.
- Pef per held weapon (swap mGoodDist / ShotPoint by weapon).
- Squad behaviour: flanking, focus fire, holding data posts.

Unknowns to pin down:
- mWpAttr bit meanings (weapon attribute table).
- EvaluateAIParam mCheckParamMode 1-11.
- mTgtType values. Seen: 0 target, 16 goal / post?, 17 weapon, 22 VS.
- mPadAction ids. Seen: 1 ride / interact, 2-3 reload, 12 pick up, 14 change weapon.
- The WAY mask (likely the VisibilityHigh / Low analyzers: the two u16 halves = standing / crouched
  visibility in 16 directions).

## C2. A brain per game mode (user, 2026-11-01)

Stock has ONE battle brain for every mode, and no filter for the game mode. Mode behaviour only appears
when its targets exist: the egg items need an egg, the post items need a post.

Posts today (`RunToDataPost` / `ExecDataPost`):
- They are only children of `Fight`, so only considered while a target exists.
- Capturing needs the post within 15 m and no enemy within 5 m.
- Weight 300 + 1000 (EvaluateDataPostOn), minus damage. Capturing aborts on 10 damage or an enemy within 4 m.
- So bots treat posts as a side task in every mode.

The user wants posts to matter far more in Post Grab than in Elimination / Team Elimination.

Plan: one brain file per mode family. Each is generated from one base by lp2think.py edit rules, so a fix to
the base reaches all of them.

| Brain | What changes |
| --- | --- |
| Elimination / Team Elimination | Base + weapon logic. Posts are opportunistic (stock weights). |
| Post Grab (Datapost) | Posts top-level, not only under Fight. RunToDataPost even with no target. ExecDataPost weight ~3000 and keeps capturing under light fire. Spread over posts: nearest unowned / contested first, defend held ones. |
| Akrid Egg | Egg items raised; escort the carrier (RunToFriend / FriendFollow); defend the goal. |
| Fugitive / Counter / other team modes | Tuned once their item sets are read (FilterTeamCommand, RunToTargetBot / RunToReaderBot). |

Loading per mode needs RE:
- Where the uHm40 bot binds its rThinkPlanAI: the reference sits in uHm6d.arc's character data, or is
  looked up by path.
- Then the DLL picks a brain by the setup's kind (setup +0x28) at match start: either a path redirect or
  swapping the resource pointer on each bot.
- Fallback if neither works: a Tier 3 custom "game mode" filter class, so one brain can branch.

## C3. Priority grabs (user, 2026-11-01)

Any pickup can carry a "bot priority" weight:
- Weapons, VS, posts, eggs, and future items such as Kill Confirmed tags.
- Set per object in the editor (inspector field, compiled into the package) and per mode (a mode's
  defaults, e.g. tags 3000 in Kill Confirmed).

Brain side: one `GrabPriority` item that scores the best flagged item as weight x distance falloff, minus
danger on the way. Stock GetWp only knows weapons (target type 17), so the item needs a DLL-side
target / evaluation (Tier 3 hook) that reads our item list.

## C4. Perception and target choice (user, 2026-11-01)

Stock:
- Bots know every enemy near them (no sight or hearing check found in the brain data).
- Once locked on, they keep the target until it dies.
- Target choice and perception are in code, not in rThinkPlanAI: uHm40 (big candidates vf94 c21480,
  vf336, vf136) and cTarget. RE: find where the bot's target is chosen and stored, and what feeds it.

New model (DLL, per bot, shared by every brain):
- **Sight**:
  - View cone: ~110 deg calm, ~160 deg alerted. Range by difficulty.
  - Line of sight: a ray against tama (bullet) collision.
  - A detection meter fills faster when the enemy is close, moving, shooting or in the open, and slower
    when crouched, still or far.
- **Hearing**: gunfire / explosions within each weapon's loudness radius, footsteps close by, and the
  direction of damage taken. Gives an approximate position, not a lock.
- **Radar**: what the bot's own radar would show under the match's radar rule (the planned Radar
  Behaviour row: Normal / moving + shooting / shooting / none). A blip = rough position -> investigate,
  never snap-aim.
- **Memory**: last known position + time. Search there, then forget after N s.
- **Team callouts**: teammates' sightings shared after a short delay (cAISvBlackBoard exists, maybe usable).
- **Target choice**, rescored every ~0.4 s:
  - Score = threat (shooting at me / damaged me recently / aiming at me) + distance + low health (finish
    off) + weapon danger + a stickiness bonus for the current target.
  - Switch when the score clearly beats the current one, or when the current one is out of sight for 2-3 s.
  - A switch costs a reaction delay.
- **Difficulty**: reaction time, aim error / settle time, cone and range, meter speed.

Hook plan: gate the stock target setter (only "known" enemies may be chosen) and override its pick with
ours. Keep the brain items (they ask "is there a target", "how far") working unchanged.

## D. Bots on any map (from the navmesh work)

- lp2navgen.py builds the LNV + WAY (done, 2335524; in-game test in Mods/navtest).
- Next: the map builder clones a TUTOREAL bot area for a package. The clone carries the nav, Pef_Hm40,
  rIntelligenceBox (empty or generated) and the package's stage / collision refs. Then the Bot Match
  screen lists packages with `"navmesh": true`.

## Order

1. An xfs.py writer, checked by a byte-identical round trip of the three brains and Pef. Then
   lp2think.py edit / build.
2. Bot Match entry + screen (RE steps A1-A3), stock bot maps, with the rows wired to the existing bot code.
3. Tier 1 weapon logic as an "Improved" brain + per-mode brains (C2: Post Grab first). The user tests them against Stock.
4. Perception / target choice RE + model (C4); VS piloting RE + Tier 2.
4b. Priority grabs (C3) with the editor field, when Kill Confirmed tags are built.
5. Package bot areas (D), then Tier 3.

## Status 2026-11-01 (night session)

DONE + installed (Steam copy; retail gets the DLL, but the bot hooks are unported there):
- xfstree.py: a lossless XFS read / write. The brains, Pef and 114 area files round-trip byte-identical;
  rAIFSM (object references) doesn't parse yet.
- lp2brain.py builds Mods/bots/nativePC/arcLp2Xml/autoArc/uHm6d.arc: stock + HumanBotBt_{elim,team,post,fox,egg}.
  - Base for every mode:
    - ShotClose (shotguns, <=15 m, prefer <6 m) under a new RunToTargetClose (arrive 2.5 m).
    - ShotLong (long range, 12-60 m, prefer >25 m). ShotHeavy (rockets, 7-40 m, penalised <10 m).
    - The stock ShotTaregt now only for other weapons.
    - WpChange-Close / -Far / -HeavyClose / -Long: range swaps, only when the OTHER weapon suits the range.
  - post: ExecDataPost for any post on the map (was 15 m). Weight 2200 (was 300). Aborted only by an enemy
    within 2.5 m or 60 damage. The run to the post survives 150 damage.
  - egg: GetEgg 3000, RunEggGoal 1500, RunToGoal_Egg 1200, FriendFollow 1500.
- DLL src/mods/bots.cpp (uncommitted by design):
  - Brain swap at spawn: think setter DX9 f7f0f0 / DX11 f8f060. Mode from game +0x8174.
  - FilterWeapon mWpMode 3 = the other weapon: DX9 980410 / DX11 98fd90. Held / other weapon: DX9
    +0x1678 / +0x1694, DX11 +0x1688 / +0x16a4.
  - Personalities via cAIPlanEvaluateAIParam::vf5 (DX9 982c80 / DX11 992600). cAIParam block at unit
    +0x2418 / +0x2428, bytes x 0.01.
    - Archetypes: aggressor / tactician / cautious / show-off / grenadier, logged per bot.
    - Taunt (Appeal1 after a kill, pad 26) gated by a per-bot 4 s roll: 70% show-off, 40% aggressor,
      25% grenadier, 15% tactician, 5% cautious.
    - Only in bot-match areas (game +599 == 0).
- Weapon masks, AIParam modes and the game kind enum are decoded (lp2brain.py docstring, bots.cpp header).
  Game kinds: 1-3 Elimination, 4-6 team battles, 7 VS, 8 Post Grab, 9 Counter, 10 Fugitive, 11 Akrid Egg.
  InitPos / ObjSet name table at DX9 0x173c3dc.

USER TEST (log lines "mods: bots:"):
- On install: "per-mode brains on".
- At spawn: "game kind N -> brain HumanBotBt_x (loaded)". If it says "missing", the game didn't find the
  overlay entries.
- Each bot: "<unit> is a <archetype>".
- Watch for:
  - Shotgun bots closing in, rifle bots hanging back.
  - Bots swapping weapons by range.
  - Post Grab (AI Enemy Battle game type 3) bots rushing posts.
  - Show-offs taunting after kills.
- Undo: delete Mods/bots (stock brain) and/or the DLL's bots hooks.

Bot Match screen RE (not built; next session, needs in-game iteration):
- AI Enemy Battle start = aTrainingTop::vf7 (DX9 8a0250). On menu state 5 it calls
  FUN_0082c9a0 thiscall(*(0x18c0c34), 0, (phase*5 + map)*5 + 1 + rule): the scene switch to the area
  class from the table at 0x17365a8 (16 B: cat, num, DTI at +0xc).
  - Bot areas are 51 + map*5 + rule.
  - map: 0 ONLINE_12, 1 ONLINE_10, 2 ONLINE_12 (block layout 2, Train_36), 3 ONLINE_01, 4 ONLINE_09.
- The bot area's mode start (DX9 8644d0; we already hook its bot count) does three things:
  - Copies the 0x64-byte rules block from match setup (0x18427b0) +0x28.
  - Sets the kind by area: 51+5k -> 1, 52 -> 4, 53 -> 8, 54 -> 9, 55 -> 11. It also sets [1]=[2]=0 and the
    offline flags.
  - Applies the block with FUN_00863540(block).
  => Bot Match = pick the area by kind family + map, start it as above, and swap our rules block in at
  that FUN_00863540 call.
- Match setup +0x78 / +0x79 = area category / number for online starts (FUN_007cf170 / 7cf1c0 set the
  game's +599 / +0x25a).
- Open: the create-match screen keeps a 0x38-byte "rules bytes" record (rules.cpp). It needs mapping to the
  0x64-byte setup block: find where the system-link start converts it (watch setup+0x28 writes after Create).
  - UX option with less Flash work: a create-screen row "Match: Online / Bots (offline)". On Create with
    Bots, call the start above instead of creating the session, plus a Bots row (count) and the existing rows.

## Grapple for bots (2026-11-03, user: bots drive like a pad, so they should grapple like players)
- Grapple = weapon uWp00, reach 1100 cm (map-editor-plan.md, navmesh). Pad action 10 = anchor (Controls plugin
  table: "grapple" id 10, <ACT_ANCHOR>); brains press pad actions through cAIPlanMoveHmAction (appeal = 26).
- To try: a HumanBotBt node pressing action 10 while aimed at an anchor point; the navmesh then needs grapple
  links (from-point, anchor point, landing region) that lp2navmap already finds (regions joined by the grapple).
- No stock human AI grapples that we know of (only uAk13 has mAnchorCmd).

## Bot rows on AI Enemy Battle (2026-11-03, built + installed, IN-GAME TEST PENDING)
- botrows.as generalised: items 2-8 cloned from Game Type; lp2BotRow(n, label, value) + lp2BotOrder("4,0,1,...")
  lays the shown rows out from one gap above Map (hidden Survival / Respawns leave no gap).
- New rows: Difficulty (Easy/Normal/Hard/Veteran: x0.6/1/1.3/1.6 on attacker, quickness, grenade, impatient,
  calm divided), Brain (Stock/Improved: ThinkSet skips our per-mode brains), Personality (Mixed or one archetype
  for all), Taunts (Off/Rare/Normal/Lots: x0/0.4/1/2 on the archetype's chance). rules.cpp BotMenuOptions() ->
  bots.cpp. Applied as each bot is first evaluated (so per match). Watch: 9 rows may overflow the panel; mouse ids
  BOT_MENU1+5..8 (0x233-0x236) unverified.
- Next: System Link "Bot Match" (create screen row Match: Online / Bots -> start the bot area, RE A1-A3).
- Stage 2 idea: networked bots as campaign-style NPC soldiers (co-op already syncs host-run AI enemies), not
  as players (no scoreboard slot); research whether a versus area can host them.

## A2. Bot Match entry, BUILT 2026-11-05 (src/mods/botmatch.cpp, flash/botmatch.as; all 4 builds; IN-GAME TEST PENDING)
- Multiplayer screen = aBattle + uIdBattle (flash\online\id200). The script adds mc_txtMenu5 (duplicate of row 4, depth -16360), re-spaces
  the rows to y -100..100 and the cursor to -32..32 degrees, and pushes the clip onto menuMain.itemArray, so the game's own selectItem works with index 4.
- Native input (DX11 FUN_00e80320) wraps at 0..3. Wrapper: its 3->0 and 0->3 wraps become 4; from 4 the game's Up/Down already give 3 and 0.
  Decide on 4 is ours (result 6, state fields as the game's). Result 6 in aBattle::vf7 phase 5 would mean main menu; ours does FUN_00ff8c10, mgr+0x3868 = 2,
  net+0x5a6 = 1, scene aTrainingTop, exactly what aMainMenu does for Training. Back from there still goes to the main menu.
- Mouse: stock vf28 only knows ids 0-3 and 500-503, so the script hit-tests and sends evnt 992 (select) / 993 (choose). 992 value 1 = entry installed (g_hasEntry).
  Help line: stock +0x1ac is index based, set to -1 on our row; the script calls cinescoMsg. English text only for now.
- Check in game: row position/look, cursor angle, text surviving focus changes, keyboard wrap both ways, hover + click, click with the mouse parked on another row.

## E. Bots in player matches (plan, 2026-11-05)
Goal: humans and bots in one VS match, every peer sees the bots as normal soldiers, in the scoreboard.

Findings:
- Offline AI battle (DX11 FUN_00873b80): game+0x254 = 16 slots, game+0x50188 = 15 others, game+0x256 = 1, then FUN_00828ca0(slot) for 1-15 and FUN_007f2ba0(slot).
  Slot records: thiscall object DAT_01852850 (DX9 018427b0, DX11 1.1 01853850, DX9 1.1 018427b0), 0x7c each at +0x148; +0x1b1 + slot*0x7c = "AI" (name from the CYBORG table).
  So AI is a property of a player slot, not a separate kind of match. Slots already reach the scoreboard, spawn code and results.
- Replication is per unit: cNetAct / cNetActHm / cNetActVs / cNetActAk (vf11-25 send, vf26-40 receive), cNetWep, cNetItem, cNetRule, and on the other machines the unit is
  driven by cThinkNetPuppet / HM / VS / AK. FUN_00856ac0 builds the net objects (cNetActHm at index 0x51f9 of a big block). Kills replicate as net actions and score locally everywhere.
- The bot unit is uHm26 ("model\hm\hme6\hme6", think HumanBotBt).
- Our DLL IS the session layer (xlive replacement): the game learns members, slots and connections through us. That is the main lever.

Unknowns, in the order that decides the route:
- U1 How a machine decides a slot is local, remote or AI, and what that does to the think class and to sending. Is it slot's AI flag + owner, or the connection?
- U2 Do cNetAct sends carry a slot / unit id, so one connection can speak for several units? (Akrid in co-op says at least units can; check whether the human path allows it.)
- U3 How a client gets the slot table: a host broadcast (cNetGameManager vf5/vf6?) or built per client from session members.
- U4 Does the client make a puppet for a slot with no session member behind it?
- U5 Versus area data on online maps: navmesh exists only in TUTOREAL areas and packages with lp2navgen output. Online areas need Pef/nav data (section D). What does AI do without it?
- U6 Campaign AI partners: are they the same slot AI, and do they already sync in co-op? If yes this is nearly the whole answer: follow what the campaign does.

Route (recommended): host-run bots in player slots.
1. Probe (BUILT, log only): "mods: slots:" lines at the first spawn of each match (botmatch.cpp BotMatchLogSlots). Host + client logs of one match answer part of U3.
2. RE U6, U1, U2 from the decomp; trace on a campaign co-op session with an AI partner.
3. Host: mark free slots AI at match start, reusing FUN_00828ca0, with Bots row on the create screen. Clients: same slot table via our "rules" member data (we already publish it, host authoritative), applied before the slot table is built, so the game needn't be taught a new message.
4. Sync: if U2 holds, the game's own cNetAct carries them. If not, our Steam control channel sends compact bot state and our DLL feeds the puppets.
5. Host leaves: bots go away with the match; no migration in the first version.
6. Lobby UI: bot count, difficulty, brain in the new settings menu (game-settings-plan.md). Bots not counted for Ranked; Player Match / System Link only.
Fallback if slots can't be shared: bots as co-op style NPC soldiers (host-run, synced, no scoreboard row). Works sooner, worse game.
Testing needs host + client, so this waits for two accounts; nothing beyond the probe should go to players untested.

Bot fill (user question, 2026-11-06): starting below the recommended player count with bots on should fill the empty slots. Nothing does this yet. Plan: Bots row = Off / Fill to recommended / fixed count; at match start the host marks the free slots AI until the target is met, a joiner takes a bot's slot if join in progress is possible. "Recommended" = the stock Settings 3 row "No. of Players Desired" ("Set the number of players desired to start the match."): ITEM_STARTNUM, DataNo RULE_STARTNUM 67 = 0x43, rules byte [0x15] (FUN_00e8c270). So no per-map value: a host rule, already in the rules block clients get. Fill target = that value, capped by Max Players (byte [0x12]). Still to check: value to player count mapping, and what the game does with it today (FUN callers of rules[0x15]).

Depends on: navmesh for online maps (section D) as bots need it on every map they play.

## Improved brains in the DLL (2026-11-06)
src/mods/brains.h (lp2brain.py --header, rerun after editing a recipe): five brains as COPY / ADD ops against the player's own stock HumanBotBt, 22 KB, no game file shipped. bots.cpp BotsBuildBrains adds them when uHm6d.arc opens (packages.cpp GenerateBrains, ModCache\generated). Checks stock size + CRC and each result's CRC. An overlay with its own HumanBotBt_* wins. Tested outside the game (Wine harness): output entries byte-identical to lp2brain.py and to the installed Mods/bots overlay.

## Test round 2026-11-06 (built + installed; retest)
- Menu: lp2BotOrder hid only rows 2+, so Game Type and Map stayed put when scrolled off: hides all now. Visible rows 6 -> 5 (user: one short at the bottom; exact cause not found, this gives one more scroll step).
- Multiplayer blip: the stock array is in reverse (24, 8, -8, -24); fixed.
- Improved brains: standard weapon range 30 -> 60 m; EvaluateDamageRemain (recent damage / 1000, decays) weights Avoid 3000, WaitCoverP / WaitAI-P 4000, WaitShotP / Wait -2500. Stock brain unchanged. If bots still ignore a far shooter, the next suspect is target choice: no target (+0x1194) at that range, so Fight never runs; mDmgGrudge in cThink (attacker memory) is the lead, target setter not yet found for human bots.

## Reacting to being shot (2026-11-06; built + installed, uncommitted, TEST)
bots.cpp ThinkBody (detour on cThinkPlayer's body, DX11 FUN_0093b1b0): Improved brain, AI slots, bot-match areas. Rising recent damage (+0x18b4) = hit; newest entry of cThink mDmgGrudge[16] (think+4: fighter, +8 grudge, +0xa age; writer FUN_00908a30) is the attacker; after a reaction delay (Easy 900, Normal 500, Hard 250, Veteran 100 ms) set max grudge and call the game's FUN_0090ffb0(think, unit, 0), which sets target and position. 2 s between switches. Stock's own retarget (vf33 / FUN_00909b30) needs grudge > 0x60 on a 300-tick timer.
Log: "mods: bots: slot N hit, target A -> attacker B (now C)". "attacker list is empty" = the table isn't filled for these bots, then find the attacker another way.
Built-in brains CONFIRMED in game 2026-11-06 ("bot brains added", "HumanBotBt_team (loaded)").

## Bots in player matches, test 2026-11-06 15:05
Fill, count and flags all good at first spawn (players 8, others 7, ai 1-7), scoreboard shows them, Spawn called for 1-7, but no bots in the world and no brain lines. FUN_007e3320 (stdcall) gives AI slots campaign partners uHm60+ by slot number unless game+0x8174 is 0/0xd; versus sets it to the game kind. Next build returns 0x27 (uHm27, the AI Enemy bot) in versus and logs each spawn's unit. If "no unit made" persists: resource list (game +0x5dac, FUN_007f2ba0), FUN_009ab870's class check.

## Team stacking, read 2026-11-06 (not built)
- Team = slot record +0 (FUN_00821020), written through FUN_007dec10. 0/1 in team modes; slot index otherwise.
- Lobby switch: FUN_00e94ea0 -> FUN_01010af0(team) refuses when the other team would drop below table[total]: 0-5 players 1, 6-10 2, 11-14 3, 15-16 4. So 4 humans can't all share a side in the stock lobby.
- FUN_00828ca0 (AI slot) leaves the team as it was; FUN_008202e0 default: slot parity if slots+0x30 == 1, else 0. Bots are not placed on a side yet.
- FUN_00ffa040 runs at match start in team modes, counts AI slots too, sorts by rank and can reassign: only partly read, must be understood before relying on any side.
- Plan: a Teams rule (Auto / Humans vs Bots), applied after BotsFill and after FUN_00ffa040, relaxed FUN_01010af0 when on.

## Test 2026-11-06 15:30 (AZ-Tech, Elimination - Survival picked)
- Anchor speed OK. Radar OK in FFA. Bots spawn and shoot, don't move: AZ-Tech has no navmesh for them (section D). Colours later: json or picker.
- Survival off all match: lobby advertised 0x10000001=1, 0x10000002=0 all run, panel shows Elimination / Kills, map prop right (13). Props are set in FUN_00414b30 (0x12 dwords); builder not found.
- Hit stagger was Reduced by log but felt normal to the user: check at a stronger value. Fall stagger was at default.
- Post-match 'Change Match Settings' is still the stock menu: later an overlay of the new setup.

## Navmesh in map packages, read 2026-11-06 (not built)
- AZ-Tech project (app_userdata/LP2 Map Editor/work/AZ-Tech-bba3b57b): nav IS built, assets/nav/List + Way 11-05 12:43, 635 polys, 741 dropped. Installed Maps/AZ-Tech.zip is 11-03 17:49 and holds no nav.
- lp2mapc.py never packs nav: it only reads it for the radar and the spawn check. The 'navmesh not saving' bug isn't why it's missing.
- Stock aArea_ONLINE arcs: Tool\AI\Pef_Hm40 only. aArea_TUTOREAL_51 adds rAINavigationMeshList, rAIWayPoint, rIntelligenceBox (tool\AI\AreaAI\...).
- The exe has no NaviMesh / AreaAI path strings: they're named in the area's Tool\ScrList\aArea_TUTOREAL_51, so adding files to the arc isn't enough.
- Plan: mapc adds the three files + ScrList entries; export rebuilds nav when missing or older than the project (warn, don't fail). Unknowns: does a versus area start the AI nav at all, what must rIntelligenceBox hold, does the arc still fit the memory budget.

## Navmesh packaging built 2026-11-06 (test package installed, UNTESTED)
lp2mapc: ensure_navmesh (stamp .preview/navmesh.stamp, rebuilds when map inputs change), add_navmesh (List, Way, empty rIntelligenceBox + ScrList types 29/30/31). Editor after_export refreshes the window. Release repo sync still to do. If bots move poorly: generate rIntelligenceBox goals.

## Test 2026-11-06 ~16:50, requests (user)
- Survival CONFIRMED on by the log (4 lives, display on). Slot-based check works.
- Bots only move near spawn on AZ-Tech. AZ navmesh is ONE component (635 polys), like stock Train_26 (3182), so islands are not the cause. Next suspect: the empty rIntelligenceBox (stock 52 elements, 328 B avg), then brains.
- Smarter bots priority (user): push noise / enemies in sight, then data posts, then roam if all posts are held.
- Multiplayer > Bot Match -> System Link create, every seat private, bots on for that one (built, untested). Back returns to the System Link list.
- Bot looks: FUN_00828ca0 versus branch copies the local player's set. Now faction 1-6 / member 0-3 from FUN_00f88a30, hashed by slot + lobby (built, untested). Only preset outfits so far.
- Grenades: second Setup after spawn overwrote 3 with 2: fixed (force only in spawn). Costs seen: frag 100, gum 50/70, disk 125, dummy 85, plasma 70.

## 2026-11-06 evening: roaming + spawns research (DX11 addresses; NOTHING below is implemented)
Done and installed, untested: Bots row locked in Bot Match, Ammo Supply / grenade counts hidden with infinite, Infinite row moved above Ammo Supply. DNF: System Link never records it (all writers gated on session +0x20 bit 2; FUN_00899a40 clears it, FUN_008999c0 sets it). DX11 read only.

Roaming cause: RunToPatrol / RUN use MoveTrace tgt 11 = Pef_Hm40 ShotPoint (FUN_0091bb40 -> FUN_00fb9ab0): doughnut 3-10 m, DistToPos weight -1, so idle bots stay local. Read from the file, not yet seen with bot-log.txt (ModCache\bot-log.txt turns on plan logging: use it next test).
Plan: tgt 20 (0x14, FreePoint) is unused by the stock brain. Point RunToPatrol / RUN at it in lp2brain.py (regenerate brains.h), detour resolver FUN_0091bb40 (thiscall(this, unit, think, plan, tgt, float* out, info), prologue 55 8b ec 83 e4 f0 81 ec d4 01 00 00; check ret N) and for tgt 20 return a sticky per-bot goal: noise (radar.cpp Shot hook has shot times) -> posts (plan +0x890 / items already) -> random far spawn record, new goal on arrival. rInitPosSet at game +0x52e4 (count +0x70, FUN_00fd1d60(i): pos +0x10, dir u16 +0x20, kind byte +0x26) gives reachable, spread goals. Untested assumption: MoveTrace paths across a whole map (stock tgt 5 goals suggest so). AI runs on worker threads. Whether target acquisition needs sight is still unread.

Spawn table: game +0xd6c count; +0xe80 + slot*0x100 + i*0x10 pos; +0x1e80 same dir; +0xd80 + slot*0x10 + i owner byte; +0xd70[slot] chosen index. 16 entries per slot, no bounds check in the adders.
Allowed (AI FUN_007f27d0 random pick; UI FUN_00ed44a0): i == 0, or owner == team. Spawn uses it in FUN_00ff98b0 -> FUN_00f8bfb0.
Load (FUN_0087e290): InitPos kinds 3/4/5 become points only in game kinds 1-3 (FUN_007e22d0, owner = slot, so always allowed) and 10 (FUN_007e21f0, owner 0), max 8 (local_6ac). Team modes have none: base + posts only. Stock Kojin has 4-6 kind 3 records + 16 kind 0.
Posts: FFA kinds index = game +0x4e90 (snapshot of d6c after the load loop) + post number; other modes post number + 1 (uOm71 +0xb90). So extras must go in before the snapshot, and generics + posts must stay <= 16.
More generic points: detour FUN_007e22d0, on the first call of a match also append spread kind 0 records. Editor maps: lp2layout still can't add records (xfstree round-trips, so a writer is possible); the 8 cap is a code immediate. Check picker Flash can draw more icons.
Auto-spawn: detour FUN_007f27d0 (after original) and FUN_00ff98b0 (before, human slots): pick the allowed index with least threat, write +0xd70[slot]; new rule in Player section; hide the picker. Distance part is easy. Line of sight: NO usable ray function found yet (sCollision ScrColInfo* classes are the lead; cAITerrainVisibilityAnalyzer uses baked data). Every feature needs sigport to all 4 builds.

## 2026-11-06 late: roaming built (installed, NOT seen in game)
lp2brain: roam (RUN + RunToPatrol to tgt 20; PushTarget in Fight: target beyond 30 m, 1000 + 300 attacker), post_far (elim, team: RunToPostFar / ExecPostFar replace the near post items in NoTarget, TargetDie). bots.cpp Resolve detours FUN_0091bb40: tgt 16 with no post fails (was own spot, ExecDataPost 800 beat RUN 300), also when gunfire outranks it (not Post Grab, not within 8 m of the post); tgt 20 = sticky goal per unit: gunfire within 60 m heard (radar.cpp shot ring, 3 s), else random spawn record 20 m+ away; new goal on arrival (6 m), noise after 10 s, no progress 6 s. Log with ModCache\bot-log.txt: "roams to", "hears gunfire", "gave up on", plan: lines. Untested: long paths; whether Shot fires for remote humans; target acquisition still unread.

## Idea (user, 2026-11-06, later): radar-aware bots
Under a radar detection rule, bots slow to stay off the radar as they near their target (Running & Shooting: walk or crouch; Moving & Shooting: stop and wait). Hold fire until committed, as a shot shows them for 2 s. Not for Always Show. Scale by difficulty / personality. Possible means: MoveTrace mIsPadWalk (not tried), crouch pad action (id unknown), FilterSnekingLevel (unread); DLL writes a mode byte from the radar rule as with P_POST_FREE. Needs kRunPace calibrated first ("own speed" log). Fair play: bots should also obey detection when finding targets, which needs the unread target acquisition.

## 2026-11-06 night: player match bots ran HumanBotCp (log: RunToReader, NearWait, Appeal4), so no improved brain had EVER reached a player match. ThinkSet now swaps HumanBotCp to HumanBotBt_<mode> there; brains also added to generated ID_CORE_MULTI + ID_CORE (uHm6d.arc isn't opened there). Bots held at 0 lives on the host (ControlUpdate hostBot; hold was local or g_offline only). Installed, not seen in game. Check log: "bot brains added to ...id_core", "game kind N -> brain ... (loaded)", plan items RUN, PushTarget, roams.

## 2026-11-08 halftime match fixes (installed, not seen in game)
- Spectating after a round: second half spawned the player (log: can respawn, HUD back) but the camera kept following the watched bot. rules.cpp ctl update: back in play after spectating -> g_follow camera onto own body (log "camera back on player").
- Roam: teammates all went for the same far spawn point. RoamPoint now picks among far spawn points the one furthest from teammates' goals + up to 30 m of chance.
- Posts: ExecPostFar ended in <0.1 s and bots looped run/activate/idle at the same post (plan+0x890 keeps offering it while it boots). bots.cpp: after an Exec*Post item ends, that post is off for the bot 15 s (P_POST_FREE 0, target 16 fails).
- Brain: ShotTaregt min range 8.5 m -> 1.5 m and its MoveDistance 5 m -> 1.5 m (AR bots sprinted at targets 3-7 m away), Avoid damage 3000 -> 1500, quickness 1000 -> 600.
- Setup re-entry: Back left g_setupLeaving set when the closed screen never ticked; reset when the screen is back after 500 ms.
- 2026-11-08 later: shotguns close without firing (RunToTargetClose without MoveShot); Avoid split by weapon class (Avoid / -Short / -Long / -Heavy, -800 inside the class's range); WpChange-* +800 x damage.
- Target reloading: weapon +0x210c reload timer (>0 reloading, FUN_0091f640), +0x20fc loaded, +0x20fe reserve (DX9 -0x10). AI param mode 15 is ours (EvalParam detour returns 1.0; game scale 0.01 = DAT_0136b6fc). PushReload (rifles, fire, stop 15 m) / PushReload-Short (shotgun, no fire, stop 4 m), e_param(15, 1600).
- Dodge direction: cAIPlanMoveHmAction::vf7 (0x99b390 / 0x98bb40 / 0x99b6b0 / 0x98be70) case 4 sets pad+0x1cc bit31 and pad vtable+0x14c(dir). Hook re-sets dir forward-diagonal to the target when item Avoid and >20 m, Avoid-Short and >7 m. Log "dodges towards its target". All untested in game.

## Area routing (built 2026-11-08, untested)
bots.cpp: areas = start points in 25 m x/z cells and 5 m levels (AreaCell includes floor(y/500)); nearest area weighs height x4. Links: goal points within 45 m across and 6 m up/down (else the nearest). Resolve -> Waypoint(): Dijkstra over links from the bot's area to the goal's, runs to the next area's point (the goal in its own area). A hop with no 3 m progress in 5 s is blocked for 120 s (cost +1e6). Logs: "map split into N areas, L links", "stuck going from area A to B". Known: RunToGoal -> WaitGoal ~1 s pause at each hop.

## Zones + typed links (2026-11-08, built, untested in game)
- lp2navmap.zones_and_links: kept navmesh cut into zones (manual: volumes with "zone": name first; auto: 20 m x/z cells, each
  edge-connected patch its own zone, slivers < 6 m2 merged). Links: walk (shared edge), jump (<= LEDGE_GAP across, <= 120 cm
  up/down, both ways), drop (down a ledge, one way), grapple (>= 200 cm up, in sight, scanned to 3300 cm = 3X; "length"),
  launch (impulse/velocity force volumes for players: trajectory at 60 Hz with 980 x map gravity to the first triangle
  passed down through). .preview/navzones.json -> lp2mapc map.json "nav_zones". Area921: 498 zones; 782 walk,
  778 jump, 356 drop, 1361 grapple (whole navmap run 4.6 min).
- DLL: packages NavZones -> BotsSetMap (via OnewaySetMap) -> bots.cpp areas = zones; ZoneWaypoint Dijkstra with
  kind costs; grapple links only if kBotsGrapple (false until RE: bot firing the anchor, pad action 10) and length <=
  RulesGrappleRange(). Driving: walk -> next zone; others -> link start (a) then end (b). Log "route from zone A to B by kind".
- Open: does the game's own path follow a goal across a drop / jump gap (b below / across)? Bot jump press for jump links.
- Zone editing (user idea: cut tool on the navmesh). Built: zone volumes ("zone": name) override the grid. Editor UI for it
  not yet (volume effect "Zone" + name; show zones coloured on the navmesh overlay; a cut tool = draw a line across the
  mesh -> a split plane stored as a thin zone boundary).

## Data posts block bot sight (user, 2026-11-08)
In corridors two bots run at a data post between them and then try to melee through it. Want: they see / shoot past posts
(too thin to hide behind) and sidestep left/right for a clear shot while firing.
RE so far (DX11): cAIPlanEvaluateCursorThrough::vf5 (0x9930b0) reads unit +0x1a8 (a cVirtualCursor) +0x19c "through" flag,
+0x1a0 time. cVirtualCursor FUN_00fc02a0 sets through = 1 for a unit hit (FUN_00fbd000 is a shooter-type check, not the hit)
and leaves 0 when the ray result's +0x3d5 (static collision hit, pos +0x390) is set: so the post's collision probably counts
as a wall. Not yet sure the AI uses this cursor (FUN_00f99100(0) may be the local player's lock-on result). Next: find where
bots' +0x1a8 cursor gets its ray (0x98xxxx: param_1[0x6a]+0x19c = 1 at 0098.c:8927) and the collision filter; then either
skip uOm71 collision in that ray or treat a post hit as through, and add a sidestep (HmAction dodge direction already hooked).

## Noise checking (user, 2026-11-08: bots hung around noise instead of checking and moving on)
bots.cpp Checked(): an area a roaming bot (no target, so not fighting) went through more than 1 s after a shot counts
as checked: that shot no longer makes noise goals (GoalUpdate) or fight-pass picks (RoamPoint). Reaching a noise goal
marks its area checked ("checked the noise: nobody, moving on" in bot-log). Fresh shots there count again. Untested.

## Weapon pickups / swaps (user, 2026-11-08; built, untested in game)
- User: bots don't seek better weapons, and a pickup drops whatever is held. Want: value-ranked pickups (shotguns,
  rockets over pistols), drop the worse weapon, per-personality slot preferences. Asked whether bots get their own
  random loadouts: unknown; rules.cpp now logs "player N loadout ..." (record game+0x28[slot] +0x10, 8 ids 0x04KK00VV) at spawn.
- RE (DX11): the bot's weapon target = plan +0x88c, set in FUN_00917b50 from FUN_009af7d0(character, float* dist, 0, 0,
  1, exclude list plan+0x5a8, count plan+0x5a4): the NEAREST takeable weapon unit (unit +4 & 7 == 2, flags 0x4800,
  +0x20d8 / +0xce0 / +0x1938 clear, FUN_009a9710 can-take per slot), within DAT_0140d52c, about level. Other callers:
  FUN_0091b520, FUN_009b0020. Resolve case 0x11 reads plan +0x88c.
- Plan: detour FUN_009af7d0 for bots only: call the original with a growing exclude list to get the nearest ~6, score
  value(kind: heavy 0x33/rockets > short 0x31 > long 0x32 / standard 0x30 > special 0x34 > handgun 0x0c; ammo left;
  personality bias) - distance, skip ones worse than both carried. Swap: in the HmAction detour, pad action 12 (pick
  up) with the held weapon better than the other -> action 14 (change) first, so the worse one is dropped. Needs the
  4 builds' addresses (sigport).
- Built (bots.cpp, Improved brains only): the AI calls of the search (DX11 call sites 917bf1 / 91b644; DX9 908261 /
  90bcb4; DX11 1.1 917dd1 / 91b8d4; DX9 1.1 908371 / 90be74) go to WeaponSearch: nearest 6, gain = value - worse carried
  (empty = 0; same id = ammo, only when that one is dry), score gain - 1/m; nothing better -> no target. Values: heavy 88,
  short 78, long 68, standard 60, support 50, handgun 20, x archetype leanings. HmAction: pickup press (pad +0x1c8 0x2000)
  -> change (0x8) while the held is the better (not when a handgun is one of the two: unknown whether it can be dropped).
  Logs (bot log on): "weapons near ... goes for / skips", "switches to its worse weapon before picking up".

## Link crossing: jump / grapple / launch (2026-11-08, built, untested in game)
- The think IS the bot's pad: FUN_0093b1b0 (think body) zeroes think +0x1c8/+0x1cc, runs the plan (cAIPlanMoveHmAction
  vf7: case 7 = jump |0x2, case 0x10 = anchor |0x4, 0xc pickup 0x2000, 0xe change 0x8), then the unit reads them.
  So bots.cpp ThinkBody ORs presses in after the original (Traverse()).
- Resolve stores the bot's current zone link (kind, a, b, linkSeen) in RoamGoal; only while roaming (target 20).
- Jump links: press jump within 1.3 m of a (not seams: a-b < 60 cm across and < 45 cm up). Stalled 1.8 s on any
  non-launch link: one unstick jump. Launch: walk in, force.cpp throws.
- Grapple: kBotsGrapple = true (within RulesGrappleRange). Within 3 m of a: bot cursor (think +0x1a8 cVirtualCursor,
  mCursorPos +0x60, mCursorTargetPos +0x70; same in DX9) set to b for 350 ms, then anchor 0x4. Log "fires the anchor",
  then "grapple climbed / didn't climb" after 1.5 s. Unknown: whether the anchor follows the cursor (else find uHuman's
  anchor aim source; cAITerrainAnchorAnalyzer exists but uses stock terrain data).
- Guardian nav (user's map): 33 zones, 13 groups without grapple; ~half of its 44 jump links are seams.
