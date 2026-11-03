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
