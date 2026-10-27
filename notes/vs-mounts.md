# VS weapon mounts (2026-10-27)

## Storage
rObjSet group 1 (VS, kind 2) records are 0x140 B: cObjSetDataBase (0x120 in the file) + cVsSetData's
mRightArm / mLeftArm / mRightShoulder / mLeftShoulder (DX9 fields.tsv; runtime +0x130..+0x160) as 4 x 5 B at file
0x120: u8 fitted, u8 4 (weapon category), u16 weapon id (0x41 Gatling ... 0x6d), u8 0; then mRiderParam
(00 ffffffff ffffffff 000000 everywhere = no preset rider). Empty mount = fitted 0 (stock fills id 0x41 or category 0).
lp2layout.put_object already writes marker "weapons": [[fitted, id] x4]; without it a placed VS keeps its
template record's mounts (Desecration's).

## Which mounts a VS has = its model's joints 100-103 (RA, LA, RS, LS)
Survey of 722 stock objsets (every map, campaign + online): RA / LA are fitted per placement; RS / LS are never
fitted (shoulder guns are the VS's own, e.g. GTT-11 autocannons on vs05's 102 / 103).
| base model | LP2 types | mounts | notes |
|---|---|---|---|
| vs06 bike / robot | 06 20 70 90 a0 | RA | (stock still writes LA 0x41 fitted: ignored, no joint) |
| vs16 | 16 21 71 91 a1 | RA | |
| vs00 PTX-140 | 00 25 75 95 a5 | RA LA | |
| vs01 | 01 24 74 94 a4 | RA LA | |
| vs04 | 04 23 73 93 a3 | RA LA (+RS LS fixed) | |
| vs05 GTT-11 | 05 22 72 92 a2 | RA LA (+RS LS fixed: autocannons) | |
| vs32 | 2b 32 7b 9b ab | RA LA | |
| vs34 | 2c 34 7c 9c ac | RA LA (+RS LS fixed) | |
| vsc6 / vsc9 | 26 76 96 a6 / 38-3b | RA LA | |
| vsc7 / vsc8 / vsce / vscf | 2e 2f 2a 2d ... | RA LA | |
| vs30 vs31 vs50 vs51 vs55 vs80-84 | own ids | RA LA | LP1 leftovers |
| vs56 vs66 | own ids | RA | LP1 leftovers |
| vs03 (turret column) | 03 29 53 79 99 a9 | none (150-152 built in) | |
| vs07 vs33 vs40 vs42, vscb (0x28 transport) | | none | built-in weapons |
Raw per-type stock usage (most common weapons per mount): scratchpad vsmounts.txt, regenerate with the
survey in this session's notes (rObjSet hash arcx.class_hash("rObjSet"), group 1, 0x140 B records).
