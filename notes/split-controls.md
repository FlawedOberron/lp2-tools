# Split controls + hold-to-aim menu option — RE notes (2026-10-17)

Goal (user): hold-to-aim as a menu option (under the Zoom row); Zoom split into
on-foot/scoped (shared) and in-VS. Example: zoom = right click, grenade = G on foot,
but in a VS right click fires the secondary weapon.

## Done (DLL, branch lp2-mods, built, NOT installed / NOT tested in game)

- `src/mods/controls.cpp`: hooks the single call to the pad update
  (DX11 0xf8d972 -> FUN_00f8a980, DX9 0xf7d9d2 -> FUN_00f7a9e0; pattern
  `8d 8e b0 03 00 00 e8 ???????? e8`, one hit in each exe). After the game's update it
  rewrites the five u64 action sets (pad+0x3b8 held, +0x3c0 pressed, +0x3c8, +0x3d0,
  +0x3d8) per context with "dest <- source" rules. Config:
  `"mods": {"controls": {"log": true, "vs": {"secondary": "zoom", "zoom": "grenade"}}}`
- hold_zoom (zoom.cpp) now has a DX9 layout too: site 0x9143a0, pads 0x1841fe0,
  owner fn 0x99b3b0, levels 0x14c7514, owner+0x2174 weapon, +0x2108 level.

## Context detection (UNVERIFIED — first thing to test)

- pad+0x480 = the pad's unit; unit+0x40 = what it is riding (the game's own Hm zoom
  check DX11 0x9397af reads it and calls FUN_009aa5d0 on it = category 2 + subtype in
  {4,5,0x22,0x23,0x72,0x73,0x92,0x93,0xa2,0xa3}).
- Current rule: ride alive, ride != unit, ride+0x1f == 2 -> "vs".
- Doubt: category byte +0x1f == 2 may also be humans (FUN_009aab90 picks between two
  weapon slots +0x1688/+0x168c for category 2; humans also carry two weapons).
  With `"log": true` every change of unit/ride is logged with ids (+0x1c). Test: walk,
  get in a VS (driver), get out, ride as passenger/gunner -> read the log.
- Alternative signals if wrong: the think class (cThinkPlHm vs cThinkPlVs strings exist;
  find the vtables), or the VS input helpers below.

## Pad action bits used (from padmap rounds 2026-10-16)

Foot: jump 0x2, grapple 0x4, next_weapon 0x8, crouch 0x20, fire 0x100,
grenade 0x200|w2 0x400000, reload 0x400|0x800|w2 0x200000, action 0x2000,
quick_turn 0x10000|0x20000, zoom 0x100000, melee w2 0x20, gesture w2 0x100,
teng w2 0x4000, dodge w2 0x8000000.
VS: secondary = grenade bits, zoom 0x100000 (+0x1, shared with get out
0x1|0x10|0x1000 + w2 0x20|0x40|0x80 -> 0x1 only cleared when 0x10/0x1000 absent),
brake 0x20, dash w2 0x10000000, boost 0x2|0x10|0x1000 + w2 0x40|0x80.

## Key config screen (for the menu work)

- Screen: flash\option\id501 (class ctor DX11 FUN_00f05580, vtable 0x16370d0).
- Rows: list A at 0x1636c70 (35 x {u32 label, u32 slot}), list B at 0x1636d88
  (9 rows: Evade, Dash, Drop R/L weapon, T-ENG supplier, VS Special Movement 1-4).
  State 2 = list A (FUN_00f06940), state 3 = list B (FUN_00f06e70). Draw: FUN_00f056a0 /
  FUN_00f05790 (8 visible rows, cursor +0x198, scroll +0x19c).
- Label = index into u32 table 0x1636dd0 -> MsgPC message id (EN: 77 Forward ... 94 Zoom
  In, 95 Zoom Out, 120 Mouse Speed, 121 Mouse Sensitivity, 125 KEYCONFIG_48 dummy).
  Lookup FUN_0077b280(&0x1373294, id, 0x16).
- Slot = index into the screen's u32 array +0x1e0 (45 slots) + conflict flags +0x294.
  Special slots 0x2e/0x2f are not keys: they print "%d" of bytes +0x1d2/+0x1d3
  (mouse speed / sensitivity). Draw calls FUN_00f04e10(row, char* text, 1) with any
  string -> a hold-to-aim row can show "Hold"/"Toggle" without new messages.
- Binding encoding: VK code, or mouse code | 0x80000000 (FUN_00f8e1c0). Names: table
  0x17fd228, 100 x {char* "<KEY_..>", i32 vk, i32 mouse}; FUN_00f04b60 = code -> name.
  Mouse codes: L 3, R 4, M 5, wheel up 12, wheel down 13.
- Key capture: FUN_00f05880 (scans VK 9..0xba excluding Esc/Alt/Shift/Ctrl, then mouse).
- Saved binds: options object *0x1852238: +0x22a/+0x22b mouse bytes, +0x238 45 u32
  slots (FUN_00f04c20 compares; FUN_00f060a0 resets to defaults via FUN_00f8e180).
  Same object holds the per-player control type (+0x3c + idx*0xe8, FUN_0080fce0).

## Menu plan

1. Copy list A into our memory with extra rows after "Zoom In" (label 43 / slot 0x1d):
   - "Hold to aim" (special slot e.g. 0x30, value = our setting, drawn as Hold/Toggle,
     left/right or confirm toggles) -> replaces "mods.hold_zoom".
   - "VS Zoom" and "VS Secondary weapon" (new key slots 0x30+ stored by us, not in the
     game's 45-slot array).
   Patch every reference to 0x1636c70/74 and the 0x118 / 35-row constants.
2. Labels: set the dummy MsgPC ids (125 etc.) via flashmsg.py `set`, served from ModCache
   (overlay), or hook the label lookup for our rows.
3. Store our values in a small file beside the save (or ModCache\controls.json).
4. controls.cpp: add raw-key sources (VK / mouse via GetAsyncKeyState, foreground check,
   own press/release edges) for the VS key rows; action sources stay for gamepads.

## Hold-to-aim in a VS (not done)

Hm zoom goes through FUN_00938630 -> FUN_00c78680 (only caller 0x93866d), so zoom.cpp
does not cover VSs. VS-side zoom input looks like the helper at DX11 0xf7d220 (edi =
helper: +0x4 state, +0x6 player, +0x8 pad, +0xc timer; checks pressed 0x100000 then held
with a timer). Sibling helper FUN_00f7d670 reads w2 0x400000 (secondary). Next: find
who calls these helpers (vtables) and the VS zoom state field.

## 2026-10-17 menu RE (DX11)
- Screen states (+0x190): 1 page select (FUN_00f06540; +0x194 page 0 "Controls" / 1 "Shortcuts", labels MsgPC 71/73),
  2 Controls list (FUN_00f074b0 -> FUN_00f06f30 input), 3 Shortcuts list (FUN_00f07540), 4/5 key capture
  (FUN_00f06940 / FUN_00f06e70 -> FUN_00f05880), 6 numeric row edit (FUN_00f069f0; rows with slot 0x2e/0x2f).
- FUN_00f06f30: count 0x23 (state 2) / 9 (state 3); cursor +0x198, visible offset +0x19c (0..7); input
  *(0x18e0860)+800 bits 1 enter / 2 back / 4 default, +0x330 bits 0x40 up / 0x80 down; Enter -> FUN_00f06480(4|5).
- Row draw = ActionScript calls with plain strings: _root.mc_main.setList(row,label,1) FUN_00f04d90,
  setListData(row,text,flag) FUN_00f04e10, setArrowState FUN_00f04f40; selectList / setCursor(+0x19c);
  hint _root.mc_CINESCO.cinescoMsg. -> header rows need no Flash edits.
- Leaving page select copies screen+0x1e0 (45 u32) to options(*0x1852238)+0x68..0x11c.
- Flying VS: ascend = change weapon bit w1 0x8 (wheel = 1-frame pulses, can't hold), descend guess w2 0x40000.
  In a VS the grenade button gives w1 0x1 = get out. Fly types seen: 0xda (confirmed), 0xa8.
