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
   State: Hit Stagger now scales all three hit pools + logs which runs out (ee9cab7, untested): check the log
   line first. Notes: game-settings-plan.md "Hit Stagger: split + increase".
3. **Jeep** (bit of fun): driver / gunner / passenger, original design in the Warthog spirit, run-overs. Driving
   core + test done (69cc0b2); game side next, seat table log first. Notes: jeep-plan.md.
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

## Carried over (open, from the last sessions)
- Black screen + hang at the title screen after the PC resumed (2026-11-09 12:28): all threads waiting on a lock,
  log stopped at the title; overlay hooked normally. If it repeats: test with ModCache\no-ui.txt.
- ModCache\deathprobe.on still on (5.7 MB file per death): ask before removing.
- Local commits not pushed / released (xlive, lp2-tools, lp2-editor): see memory lp2-night-2026-11-08.
- Frozen wasteland map with jeeps: asked "map first or jeep first, new map or a snowy version of an existing one".
- Screenshot fix (game's own swap chain hook) confirmed working 2026-11-08 20:16.
