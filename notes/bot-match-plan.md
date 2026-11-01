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

## D. Bots on any map (from the navmesh work)

- lp2navgen.py builds the LNV + WAY (done, 2335524; in-game test in Mods/navtest).
- Next: the map builder clones a TUTOREAL bot area for a package. The clone carries the nav, Pef_Hm40,
  rIntelligenceBox (empty or generated) and the package's stage / collision refs. Then the Bot Match
  screen lists packages with `"navmesh": true`.

## Order

1. An xfs.py writer, checked by a byte-identical round trip of the three brains and Pef. Then
   lp2think.py edit / build.
2. Bot Match entry + screen (RE steps A1-A3), stock bot maps, with the rows wired to the existing bot code.
3. Tier 1 weapon logic as an "Improved" brain (a Mods overlay). The user tests it against Stock.
4. VS piloting RE + Tier 2.
5. Package bot areas (D), then Tier 3.
