# Customise (parts) menu RE — 2026-10-18

Menu object `m` (thiscall `this`). Categories `cat` 0 hd, 1 bd, 2 bk, 3 lg.
Part code (u32): byte0 set (DLC 0x0e/0x0d, 0x0c special; |0x20 = "2e" form sent to the preview),
byte1 colour 0-3, byte2 variant, byte3 faction (descriptor tables).

## Fields
- `m+0x34+cat*4` list length, `m+0x44+cat*4` list index (current row position)
- `m+0x54+cat` colour index (byte, 0-3)
- `m+0x60` selected row (1..10): 1/2 hd, 3/4 bd, 5/6 bk, 7/8 lg (odd = part, even = colour?), 9 back/exit, 10 toggle
  (`FUN_ed4c50` row -> cat; second return = row kind 1 part / 2 colour)
- `m+0xa4` loadout index; `m+0xa8+(cat+loadout*8)*4` current code; `m+0x124` faction;
  `m+0x15c+(cat+faction*8)*4` per-faction copy of the code
- `m+0x344` preview character (null when none); `m+0x72f` ignore-faction flag; `m+0x737` alt name table

## Functions                        DX9          DX11
- menu update (input)               ed... ee0e00  ef0c20
- part step L/R (list, unlock, faction filter; DLC 0x0d/0x0e skip faction)
                                    ed4ca0       ee4ac0 (confirmed identical; called from ef0c20 @0xef0ea0)
- apply part (colour := 0, preview, name, swatch)
                                    edd900       eed720
- colour step (bails for set 0x0c/0x0d/0x0e or single-colour parts; wraps 0-3)
                                    edbb80       eeb9a0
- single-colour part predicate(code) f4d070      f5cd90
- descriptor id from (set,col,var,cat) f4cb40    f5c860   (0x100 = none)
- Flash Parts.setPartsColor(idx, cat, colour) colour 0-3 -> "A".."D", else "" (Flash shows "LOST PLANET 2")
                                    ed5240       ee5060
- part name display (DLC: name from sname via (cat, variant, 0) -> setPartsName)
                                    edbfd0       eebdf0
- DLC name lookup (cat, variant, 0) 855df0       8654a0
- setPartsName (msg id) / (DLC string)  ed5380 / ed5490   ee51a0 / ee52b0
- preview set part thiscall(preview, cat, code): prev=cur, cur=code, release old, state 4 (= reload,
  runs even if the code is unchanged)
                                    c2bb10       c3b700
- preview apply variant (cat, code, 1) c2df40    c3db30
- other swatch refreshes passing colour 4 for DLC/single-colour: DX11 eedd30 (page refresh), eebaa0

## DLC table (DX11 0x16418b4, .rdata) — checked 2026-10-18
- ONE table for all 4 categories, 70 u32 codes, index = DLC item 0-69: `0e 00 <item> <fac>`
  (set 0x0e, colour 0, variant = item, faction byte 0 for items 0-44, 4 for items 45-69).
- Readers: descriptor id f5c860(set,col,var,cat) (masks off faction) and f5c9a0(code,cat)
  (drops colour + 0x20, compares variant AND faction) -> both return 0xb4 + index = 180 + item.
- Carrier at item 69 = id 249 (unlock dword 7, bit 0x80000000>>25; mask is 32 bytes = 256 ids, fits),
  code 0x0445000e. The existing unlocker already covers it if the carrier is a normal PartPackage.

## Carrier / colour plan from this
- Colours: hook colour step (DX11 eeb9a0): our part with N>1 colours -> step through the declared
  letters, write m+0x54+cat, m+0xa9.., m+0x15d.. like the game, preview c3b700(cat, code|0x20),
  ee5060(idx, cat, colour). Swatch refreshes (eed720, eedd30, eebaa0) pass 4 for DLC: hook ee5060 or
  patch those sites to pass the code's colour byte for our multi-colour parts. Colour names: Flash
  only takes letters A-D (custom names would need a GFX edit) -> letters only for now.
- Carrier set switch: part step (DX9 ed4ca0) on the carrier id -> step our registry; reload via
  preview c3b700 (forced reload even with the same code); name via DLC name lookup hook (8654a0).
- Path builder must then see the colour byte: confirm parts+0x45 follows code byte1 (it read 0 with
  the colour step blocked).
