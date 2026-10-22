# Requested: multiplayer match-settings menu (user, 2026-10-20) — in progress (RE)

Create-match settings pages ("Settings 1" / "Settings 2"):
1. Move **Default Weapons** from Settings 1 to Settings 2.
2. New **Default Secondary**: None / Sidearm / Standard / Short / Long / Heavy / Special / Random.
   Players spawn with that secondary weapon (none = no secondary).
3. New **Weapons on Map** (directly below Set Weapons): Default (no change) / Sidearms / Standard / Short /
   Long / Heavy / Special. Non-default = every ground weapon pickup becomes that class.
4. New **Unlimited Ammo** and **Unlimited Grenades**, both default Off.
5. All of these saved with the match settings (like the stock options).

Useful facts already known:
- Weapon slot ids (objset item, 2026-10-20 slot test): 0x0c Handgun, 0x15-0x19 Frag/Gum/Disk/Dummy/Plasma
  grenade, 0x30-0x34 Standard/Short/Long/Heavy/Special; 0x41/0x43/0x44 VS mount slots. The match settings
  pick the actual weapon per slot class; pickups re-roll at Go.
- "Weapons on Map" could be done by rewriting objset group 4 item ids (+0x1A) at load, or in the slot ->
  weapon resolution (better: also covers stock maps).
- Menu is the create-match flash (aBattlePlayerCreate.arc rFlash/rFlashDef, ID221_*). Needs RE of how the
  settings pages are built, stored and sent to joiners (host-authoritative? must sync for clients).

Planned order (user): map sync + part sync next week; this after or alongside.

## RE progress (2026-10-20, DX11)
- Flash: aBattlePlayerCreate.arc flash\playermatch\id221 (GFx; FFDec -export script -> frame_1/DoAction.as +
  __Packages/OnlineRule.as, DataNo.as, MsgOnline.as). Pages = OnlineRule.mainItemArray / sub1ItemArray /
  sub2ItemArray [catg][row] of ITEM_* ids (ITEM_WEAPON = 15, in every main page row 6/7; sub1 = CUSTOMIZE,
  ABILITY, GRENADE, SETWEAPON, SETGRENADE, SETVS, REFEREE; sub2 = STARTNUM, RESPORN, WEATHER, (TEAMCHANGE,
  HALFTIME, PENALTY, KICK,) PCCROSS). offsetArray[item] = [MsgOnline value base (-1 = string), DataNo].
  Row label = MsgOnline 38 + item. Values read with IGame.getNumber(DataNo) (FWData kind PLAYERMATCH_CREATE).
- FWData kinds: .rdata table of 12-byte {name ptr, buffer, slot count} records (PLAYERMATCH_CREATE @ file
  0x141f7f8, 0x80 slots -> DataNo 75..127 free for new rows). DataNo 50..74 = RULE_* (Flash DataNo.as).
- C++ setter for this kind: FUN_00f4a330(dataNo, value). FUN_00e8c270(rules) pushes every rule (callers
  e8f260, e90180). Rules byte struct: [1] time, [2] respawn?(0x46), [3] DEFAULT WEAPON (0x38; 5 = random ->
  [0x23]), [4] grenade (0x3e via remap {6,0,1,2,3,4,5}; 6 = random -> [0x24]), [5] set weapon (0x3f),
  [6] set grenade (0x40), [7] set VS (0x41), [8] attack/FF (0x3a), [0xf] settype, [0x10]/[0x11] 0x48/0x49,
  [0x12] maxjoin (0x35), [0x13] private (0x36), [0x15] 0x43, [0x16] main catg (0x32), [0x1b] map (0x37),
  [0x20] 0x45, [0x26] 0x47, [0x27]/[0x28] customize/ability, [0x29] 0x42, [0x2a] 0x44.
- Create screen controller FUN_00ef6810 (page +0x194, row +0x198+page*4, row counts +0x4f8/+0x4fc...).
  Next: find the C++ per-page row tables / L-R value handlers (callers of e8c270 e8f260/e90180), rules size
  + where it is saved (Saved Match settings) and sent to clients; then the spawn-loadout and pickup code.

## RE progress 2 (2026-10-20, DX11) — the row model
- C++ rows: FUN_00e8c5a0(mainCatg, subCatg, page, row) -> **rules byte offset** of that row, from a
  table at 0x17e9840: 17 records x 0x23 bytes {main, sub, ?, items[page*0xb + row]} (3 pages x 11).
  The stepper edits rules[offset] directly (caller passes rules+offset).
- Min/max per offset: FUN_00e8c690 (switch on offset; out params max, min). Wrap flag per offset:
  byte table 0x17e97b0[offset] (0x30 entries). Help/desc id per offset: u16 table 0x17e97e0[offset].
- Stepper FUN_00e8c910 thiscall(screen, key 10 R / 11 L, u8* value, max, min, offset, wrap) -> changed;
  on change the caller does f4a330(10,..), FUN_00e8fd50(offset) (side effects), e8c270(rules) (push all
  to Flash). **Hooked already** for the map picker (maps.cpp RuleStep).
- Rules struct = **0x38 bytes**; saved slots at game+0x104, 6 x 0x38 (FUN_007fb500 init). Defaults
  FUN_008219b0 set offsets up to 0x2d -> **0x2e..0x37 look unused** (10 bytes): new options can live
  there and be saved with the match settings for free (verify nothing reads/writes them).
- Session: FUN_00829180 converts rules bytes -> session struct of ints (sent to clients); our new bytes
  are NOT in it -> sync our options via our own lobby data key (host-authoritative).
- Flash rows are separate: OnlineRule.as arrays [catg][row] of Flash ITEM ids (0..33, differ from the
  C++ offsets), offsetArray[item] = [MsgOnline value base, DataNo]; labels MsgOnline 38+item.
  Values come from IGame.getNumber(DataNo) pushed by e8c270 -> add our DataNos (75..127 free) in a hook
  after e8c270.

## Plan
1. Flash: append a DoAction tag to id221 frame 1 (generated at runtime into aBattlePlayerCreate.arc,
   like the thumbnails) that pushes our ITEM ids into the sub arrays + offsetArray entries; message
   strings appended to MsgOnline (labels + values). Moving Default Weapons = edit both row arrays.
2. C++: patch the 0x17e9840 row table (copy) to the same layout with offsets 0x2e.. ; hook e8c690 for
   their min/max; wrap/help tables extended (copy tables or handle in RuleStep).
3. Sync: host publishes the options as lobby data; clients apply.
4. Gameplay RE (each its own): spawn secondary, pickup class rewrite, unlimited ammo, unlimited grenades.

## Weapon respawn (PINNED 2026-10-20)
- rObjSet weapon records (group 4, 0x120 bytes): +0x78 u32 = 0 on ~87%, else 500-5000 (mostly heavy/VS
  mounts; Kraftwerk Team-03 has 1000 on nearly all). Assumed respawn delay, UNCONFIRMED.
- Live test (DX9, Kraftwerk + Cube Team Elimination): hw read-watch on +0x78 of all loaded copies = no
  reads during play (game copies them at load). Picked-up / dropped weapons did NOT respawn in 10 min.
- Object field names (cObjSetDataBase props, DX11 fdab..): Scale +0x60, mUserData[0..] at +0x84 step 4.
- Stock Settings 3 has Respawn On/Off (DataNo 68, "Turn respawn function on or off").
- Ideas queued: Custom ammo (JSON per class, host sends table in rules), Survival (lives on Battle Gauge).

## Grenade infinity
- HUD left counter DX11 ecac50 / DX9 ebae50 (setWPL%d; count clamped >= 0 by caller ed51d0, so no -1).
  Counter sprite 154 in id751_PC_<lang> is shared with WPR; frame 7 (style 6) = infinity.
- Icon getter DX11 ed1e00 / DX9 ec1ff0 thiscall(hud, weapon, a, b, c): grenade icons recorded, then the
  left counter gets style 6 for them while unlimited grenades is on.

## Survival (started 2026-10-20)
- Menu: sub-type row shows Survival between Kills and Points (Elim + Team Elim). Game keeps sub=1 (Kills,
  category + rows unchanged), rules byte 0x32 = survival flag. Sub-type row label reads DataNo 79 via
  offsetArray[1]/[2] = [630/640, 79]; texts 630.. / 640.. alias game msgs 79-82 / 83-87, +2 = "Survival".
  Flash category = OnlineRule.getCatgNo(MAIN_CATG, SUB_CATG) (frame_1 DoAction updaateItemCommon).
- Match data: class cInfoGame (vtable DX11 0x16447f0, props fn f75de0), embedded at owner+0x3e0 (owner
  vtable 0x136ee88, ctor 811830, stored at mgr+0x144b4). Props (offsets from cInfoGame): gameTimerMax
  +0x358, mNetWork.dieCountPerson +0x35c (type 0xa x 0x20), dieCountTeam +0x39c, killCountEnemy +0x41c,
  warPotentialPerson +0xc5c, warPotentialTeam +0xc9c. isGameFinished string ref 82784d.
- Next: DX9 ports; runtime check of the die counts (user plays DX9); respawn block for 0 lives; end of
  match + winner (most lives, score tiebreak); HUD lives.

### Survival spectator (2026-10-20, WORKS in training bot match, DX9)
- Out player held in controller state 1 (death view): timers +0xfc/+0x100 kept >= 1, any 2..5 pushed back to 1.
  State 3 = respawn dialog, which grabs the camera (spectating there only lasted a second).
- Update object (8ff650 this) != per-slot entry. Entry = pad = DX11 0x1852080 / DX9 0x1841fe0 [slot];
  entry+0x480 player (+4 &7 in {1,2} active, +0x40 body), +0x484 camera (local only), +0x3b8 held actions.
- Follow: DX11 8e5e30 / DX9 8d64d0, thiscall(cam, body, 0xff, [16f7c6c / 16e7098] float, 0.0f); cam+0x200 = body.
- Fire = next player, zoom = previous; auto-switch on target death. Local slot fn returns -1 offline -> slot with camera.
- Test switch: ModCache\survival-test.txt "respawns=N;team=0|1" forces Survival (training has fixed rules). Delete after testing.
- TODO: hide HUD (T-ENG etc.), match end (last standing / most lives / score), lives HUD, MP test.

### Survival end + training rows (2026-10-20, end of session) — UNCOMMITTED, installed (backup xlive.dll.pre-botmenu)
- WORKS (tested): hold in death view, spectator follow + fire/zoom switch, bots held offline (no lobby = g_offline),
  match end when 1 player/team left (EndCheck hook DX11 1008ef0 / DX9 ff8b10) -> defeat screen shown.
- Ranking hook (DX11 1009b90 / DX9 ff97b0): resorts by respawns left*100000+score; training rule = 1 (added).
  UNTESTED after adding rule 1: check winner order + whether encoded score shows on results screen.
- AI Enemy Battle rows (UNTESTED): flash/botrows.as (src/mods/flash, compiled -> botrows.h via FFDec -importScript),
  injected into aTrainingTop.arc id300 root; hooks BotCursor f44680/f34940, BotStep f44760/f34a20,
  Flash call f4a390/f3a660 "lp2BotRows", input global 18e0860/18ce774 (+0x330), sound 832f00/824110.
  Menu: +0x190 state, +0x194 phase (2 bot), +0x198 rule, +0x19c map, +0x1b0 row. Cursor angles guessed 216/240.
- survival-test.txt removed (override code still in SyncThread).
- NEXT: user screenshot of bot screen + test rows; bot count (not on screen, from map/rule setup; aiSlot/isBot);
  hide leftover HUD while spectating; respawns HUD; MP test; commit after approval. Bot AI = PINNED (out of scope).

## Spacewar (480) networking plan (agreed 2026-10-21)
- Steam copy (default): game process stays 45750 (achievements, DLC, cloud, presence). DLL spawns a
  helper exe running as AppID 480 for lobbies/invites/P2P only; local pipe between DLL and helper.
- Config `"non_steam": true`: no helper, whole DLL inits as 480 (SteamAppId env forced), cloud sync
  off, DLC/achievement calls skipped. Steam client must run.
- Both share 480 lobbies (filtered by title id + add a build-version key).
- Steps: 1 abstract lobby/P2P calls (xsession/xlocator/net/transfer/memberdata/discord use Steamworks
  directly) behind local-API vs helper-pipe; 2 helper exe; 3 invites/join via helper; 4 non_steam flag;
  5 disc exe address port (needs a disc player's exe; sigport).
- Why not a plain 480 switch: one AppID per process -> DLC BIsDlcInstalled answers for 480, achievements
  and Steam Cloud go to Spacewar.

## 2026-10-21 committed b1f016c (pushed)
Bots row (mode start DX9 8644d0 / DX11 873b80: loop imm + players+0x254 + players+0x50188; setup+0x70
= results PLAYER_MAX; results present-check je DX9 e9a44a / DX11 eaa1ba NOP'd), conditional rows,
bottom bar text hook (DX9 f36170 / DX11 f45eb0), body removal (ctl+0x40 vtable+0x30, as respawn
DX9 8f057f / DX11 8ffedf), HUD off while spectating (status [DX9 18c080c / DX11 18d08ac]+0x14594 bit
0x4000000), save import (saves.cpp).
NEXT (user order): 1 in-match left player list (name + Battle Gauge, native sprite list, likely
uIdBattle / SprLayout ranking00) -> lives left / ELIMINATED red, FFA first; 2 teams; 3 Spacewar layer.
- Map gimmick: animated crusher on a training/online map (2026-10-21) - look at how it is driven (gimmick/script object) for custom maps.

## Team Elimination HUD (2026-10-21, DX9 VAs; port with sigport)
- Team Elimination = setup(0x18427b0)+0x28 == 4 (5 = team kills rule, shows mc_Kill). Left rows = Flash id762 (x/flash/cockpit) `_level0.mc_Kill`, anchored left_top:
  Point_RED/Point_BLUE, setKillRed/Blue(5 digit sprites + infinity), setState(0..3 topBlue/topRed/change*). No text fields/fonts in id762.
- Updater ecbd70 (cockpit this): kind==5 -> +0x1e70 = results(0x1842198)+0x197c (red kills), +0x1e74 = +0x1980 (blue); calls ebf710 (setKillRed, kills + target 0x181fc60[setup+0x4c]) / ebf850 (Blue) / ebf990/ebfad0 (First*).
- mc_TEAM (id755 top bar, setTeamGauge ebb1a0, from results+0x107c/+0x1080 via ec63d0) shows for kinds 4/7 (incl. Team Elimination); hidden by our TeamBar detour while Team Survival is on.
- Native list ec4df0 returns at once for team kinds (fe8c70: kind 0 or 4..11) -> free to draw our own native text rows there (sprintf + 80ead0 like the FFA list).

## Bots on every map: findings (2026-10-22)
- AI Enemy Battle map row = menu +0x19c (0-4), game type +0x198 (0-4); records [phase][rule][map] at 7d81f0 (DX9);
  picture = Flash frame `stageImage` (f35f90), so the menu's art is fixed per index.
- Each bot match is its own area: aArea_TUTOREAL_51..75 (5 per map): 51-55 / 61-65 ONLINE_12, 56-60 ONLINE_10,
  66-70 ONLINE_01, 71-75 ONLINE_09 (26-50 the same maps for the other training screens).
- Bots need `tool\AI\NaviMesh\Train_NN\List_Train_NN.rAINavigationMeshList` (magic LNV, v9, ~500 KB) and
  `Way_Train_NN.rAIWayPoint` (magic WAY, v16, 0x4f5 points in Train_26). Online areas (and so map packages)
  have only Tool\AI\Pef_Hm40, no navmesh -> no bots there; system link would also need networked AI.
- Plan: RE LNV + WAY, view in Blender, generate from lp2col walkable collision (map builder), then a bot area
  per package (clone TUTOREAL_51 refs + generated mesh) and extra rows/indices in the bot menu.
