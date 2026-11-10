# LP2 roadmap

"What's next" starts here. This week's list is the user's own (2026-11-09), roughly in their order; each item
points at its detailed notes. Older long-term lists stay where they are (map-editor-plan.md "Roadmap",
later-2026-11-03.md ROADMAP items, mode-scripting-plan.md, bot-match-plan.md).

## This week (from 2026-11-09)
1. **Character importer: pose bones before rigging.** Let the user pose / adjust bones to match the model when it
   isn't in the exact rest pose, then rig. Godot app ~/Projects/lp2-charedit (importer.gd, export.py); still
   untested in game.
2. **Stagger settings: fix + split.** Fall, melee, hit (bullet), grapple (anchor) and explosion, each with
   reduce AND increase options (anchor hit sending players flying). Later: melee ragdolling people off the map.
   State 2026-11-09: split built (xlive "Stagger split" commit, untested in game): Bullet Stagger (the old Hit
   Stagger row, rule byte 0x36) + Explosion / Anchor / Melee Stagger rows (extras), values Default / Reduced / Low /
   Off / Increased 1.5x / High 2x / Extreme 3x. Kind from the caller's return address (melee, anchor) or the third
   pool (explosion), all 4 builds. Not yet: anchor hits launching players, melee ragdoll off the map.
   Notes: game-settings-plan.md "Hit Stagger: split + increase".
3. **Jeep** (bit of fun): driver / gunner / passenger, original design in the Warthog spirit, run-overs. Driving
   core + test done (69cc0b2). PARKED 2026-11-09: in-game hack attempts failed (walks like a VS); user's 7-step
   plan + findings in jeep-plan.md; user is learning hard-surface modelling and will design a generic vehicle.
   Test files removed from both game copies (map zip, Mods\jeep, ModCache\jeep.txt); the DLL code is inert without
   jeep.txt.
4. **Custom weapon + vehicle logic, custom animations** (start). Notes: weapon-workbench.md (WpXXParam stats in
   exe data), map-editor-plan.md (LP1 VS logic, VS weapons e.g. Welding Beam), vs-ids.md, vs-mounts.md. Mode
   packages (GameModes zips, content.weapons / vehicles) are the intended carrier.
5. **Weapon skins**: same weapon, new visuals (model / textures swapped per weapon, like parts).
6. **LP1 characters as skins: a decent workflow** (now a mess). Notes: handoff-2026-10-18c.md "LP1 character
   pack" (8-bone skin type 5/8 second VB undecoded, black heads, joint map LP1 -> LP2).
7. **Post maps and parts on ModDB** so active modding is visible (lp2-mapedit release repo for the editor; pick
   finished maps / part packs, screenshots, short descriptions).
8. **Bots: less dumb.** Open: grapple aim (anchor fired but didn't climb), jump links, data posts blocking sight,
   handgun swaps, bot driving later. Notes: bot-match-plan.md (Link crossing, Data posts, Weapon pickups).
9. **Vehicle locational damage** (experiment, if there's time): hits to wheels / legs / engine / turret parts
   doing different things. Lead: uVitalSuit mWeakHitParts / mWeakHitRemainTimer / VsWeakDamageTurnAngle (the game
   already has weak-spot parts), mIsMovePartsBreak / mIsJumpPartsBreak / mIsDurabilityPartsBreak.
10. **Frozen Wasteland (jeeps)**: LP2's stock Frozen Wasteland (online map 15), unchanged stage, with a bunch of
   jeep spawns in every layout. NOT the LP1 s850 port (user, 2026-11-09). Needs: (a) the jeep in game (item 3)
   and a jeep spawn record / marker kind; (b) a stock-map variant package: map 15's files copied into a package
   (base 15; packages are bound to slots 13/14 and renumbered, so the stock files have to travel in it) with its
   layouts (start / object sets) patched to add the jeep spawns (lp2layout.patch_objset). The editor has no
   "keep the stock stage, edit layouts only" project yet: add that (useful for other stock-map variants too).
   2026-11-09: first cut built by script, untested: lp2jeepmap.py -> Maps\FrozenWastelandJeeps.zip (every layout's
   VS spawns -> type 0x16, which lp2jeepmodel.py's uVs16.arc override dresses as the jeep; ground inside).
11. **NEXT after stagger (user, 2026-11-09): "change game settings" from the lobby**, so the host doesn't back
   out and recreate the match each round (was "post-game game settings menu"). Related: game-settings-plan.md (our own rule storage, presets per game type),
   requests-mp-menu.md.

## Carried over (open, from the last sessions)
- Black screen + hang at the title screen after the PC resumed (2026-11-09 12:28): all threads waiting on a lock,
  log stopped at the title; overlay hooked normally. If it repeats: test with ModCache\no-ui.txt.
- 2026-11-09 cleanup: test files removed from both copies (mode.txt Survival FFA, deathprobe.on + 325 MB dumps,
  bot-log.txt, scorelog.on, team-hud.txt, jeep files). Kept: fonts.txt, rules.txt, README.txt, steam_appid.txt.
- Local commits not pushed / released (xlive, lp2-tools, lp2-editor): see memory lp2-night-2026-11-08.
- Screenshot fix (game's own swap chain hook) confirmed working 2026-11-08 20:16.

## Requested 2026-11-09 (later)
- Damage modifiers per attack type (bullet, explosion, anchor, melee, fall, VS weapons...), taken and dealt, plus a headshot modifier. Rows in Match Settings (setup + lobby). The hit kind detection from Hit Stagger (StaggerKindOf, rules.cpp) can be reused; damage entry DX11 0x9b71b0 (map-editor-plan.md), uCharacterBase::vf151 hit handler 0x9d4210.
- Random map choices including custom maps (game-settings-plan.md, lobby phase 2 TODO).
- Bot AI: F.E.A.R.-style GOAP planner for Team Elimination (cover points from collision, LOS, squad roles), after the lobby menu.
- Voice chat settings (user, 2026-11-09): an options page for voice (on/off, push-to-talk vs open mic + key, input/output device, volumes, mute per player). Find how the xlive voice path works today (XHV / Steam voice in xlive-steamworks) before designing.
- Voice chat rules (user, 2026-11-10): BUILT, untested (xlive b628e97, not installed yet). Host rules Team Voice / Enemy Voice (one Voice Chat row outside team games): Always, Living, Nearby (full to 15 m, gone at 30 m), None. mods/voice.cpp; applied where voice is played, talker -> slot from member data "vslot". Needs a 2-player test.
- Bots on stock maps (2026-11-09): navmesh now loaded per stock area (stockarea.cpp); zones grouped into regions for roaming (bots.cpp RegionsBuild). Map 12 nav still poor.
- Stagger rows (built 2026-11-10, untested in game): Headshot, Airborne Bullet, Airborne Headshot (rules.cpp HitIsHead, CharacterAirborne). Not counted as airborne yet: hanging still from an anchor.
