# Lost Planet 1 maps → Lost Planet 2

Port a Lost Planet 1 (Colonies) multiplayer map into Lost Planet 2 as a `Maps\*.zip` package for
[Lost Planet 2 (Recolonised)](https://github.com/FlawedOberron/xlive-steamworks-lp2), and optionally edit its
spawns, VS, weapons and data posts in Blender.

**Status: experimental.** Battlegrounds and Area 921 have been ported this way. Geometry, movement and bullet
collision, grenade physics, spawns, VS, weapon pickups and data posts work in game. Lighting is a generic
daylight, and maps keep stock Desecration's radar map and music.

Nothing from either game is in this repository. Every file in a package is built from your own copies of
the two games.

---

## What you need

- **Lost Planet 2** on Steam, with the Recolonised `xlive.dll` installed (it loads `Maps\*.zip`).
- **Lost Planet: Extreme Condition – Colonies Edition**, Xbox 360 disc image. Its `ZZPack2\sNNN.arc` files
  hold the multiplayer maps. The PC release of LP1 lacks the Colonies maps (s92x), so the tools use the
  360 data for every map.
- **Python 3** with `numpy` and `Pillow` (`pip install numpy pillow`).
- **Blender** 4 or newer (tested with 5.2), only for editing layouts. The commands below use the Flathub build
  (`flatpak run org.blender.Blender`); with a normal install, run `blender` instead.

## LP1 map ids

| Map | Id | Map | Id |
|---|---|---|---|
| Canyon 810 | s810 | Radar Field | s901 |
| Pirate Fortress | s820 * | Island 902 | s902 |
| Lost Coast | s830 | Hive Complex | s903 |
| Dilapidation | s840 | Trial Point | s904 |
| Frozen Wasteland | s850 | Lost Technology | s905 |
| Crimson River | s870 | Ruins | s906 |
| Training Facility | s880 | Ice Drop | s907 |
| Dark Town | s890 | Crossfire City | s920 |
| Battlegrounds | s900 | Area 921 | s921 |
| Lost Arena | s922 | Assault Space | s923 |

\* Pirate Fortress draws its terrain from campaign stage s122, which lives in another archive. `lp1map.py`
only reads the map's own archive, so that map isn't supported yet.

---

## 1. Get the LP1 map archives

```
python3 xiso.py list "Lost Planet Colonies.iso" ZZPack2/s9
python3 xiso.py x "Lost Planet Colonies.iso" lp1 ZZPack2
```

This extracts `lp1/nativeXenon/ZZPack2/s810.arc ... s923.arc` (and the rest of ZZPack2). `xiso.py` only
reads the image.

## 2. Build a package (one command)

```
python3 lp1map.py --game "PATH/TO/Lost Planet 2" --lp1 lp1/nativeXenon/ZZPack2/s921.arc \
    --name "Area 921" Area921.zip
```

Copy `Area921.zip` to `Lost Planet 2\Maps\` while the game is closed. It shows up in Create Match's map picker
under its name, and lobby members who lack it download it from the host.

Takes about a minute and a half. What it does:

| Step | Tool | Result |
|---|---|---|
| Base | (copied) | stock online map 00 (Desecration) from your LP2 folder |
| Stage | `lp2stage.py` | LP1's stage models (and sky dome) as one LP2 stage model + textures; LP1's lightmaps are baked into vertex colour |
| Collision | `lp2col.py` | movement (`atari`) and bullet (`tama`) collision with LP2's BVH |
| Physics | `lp2havok.py` | Havok mesh for grenades, debris, ragdolls |
| Layout | `lp1points.py`, `lp2layout.py` | LP1's spawns, team spawns, VS (LP1 types) and weapon spots in every game type; markers just under the floor are lifted onto it |
| Light | `lp2light.py` | static daylight, lighting zone bounds, an intro camera orbiting the map |
| Paths | `arcsub.py` | resources renamed `scr\Online\online00\` → `scr\Online\<tag>\`, so the game never mixes them up with Desecration or another port |
| Occluders | | emptied (Desecration's would hide the new geometry) |

Options:

| Option | |
|---|---|
| `--tag NAME` | the 8-character resource folder (default `lp1sNNN_`). Two packages must never share one |
| `--size small\|medium\|large` | lobby size class (default large) |
| `--layout FILE.json` | use a layout exported from Blender (step 3) instead of LP1's |
| `--sun X,Y,Z` | direction towards the sun, Y up (default `0.472,0.848,0.241`), `--tint R,G,B` its colour |
| `--sky R,G,B`, `--bloom R,G,B`, `--curves ...` | filter overrides, see `lp2light.py` |
| `--thumb IMAGE` | create-match thumbnail from any picture (a screenshot works); `--zoom 1.5`, `--at 0.6,0.5` frame it |
| `--exclude TEXT` | leave out LP1 stage models whose name contains TEXT, e.g. `--exclude _sky` |
| `--work DIR` | keep the intermediate files (to inspect, or to run single tools again) |

### Package layout

```
Area921.zip
  map.json                {"name": "Area 921", "base": 0, "number": 0, "size": "large"}
  thumbnail.rTexture      optional
  nativePC/...            the map's files, named as map 00
```

The DLL gives each package a free map slot at run time, so any number can be installed.

---

## 3. Editing the layout in Blender

LP1's layouts work as they are. Edit them when a map needs balancing, more data posts, other VS, or
weapon pickups placed by hand.

### 3a. Make a map .blend

```
python3 arcx.py x lp1/nativeXenon/ZZPack2/s921.arc s921
mkdir s921obj
python3 lp1model.py s921/scr/stage9/s921/s921.0x1041bd9e s921obj/s921.obj
flatpak run org.blender.Blender -b --python blender_obj2blend.py -- . --scale 0.01 --merge s921 s921obj/s921.obj
python3 lp1points.py lp1/nativeXenon/ZZPack2/s921.arc s921.json
flatpak run org.blender.Blender -b s921.blend --python blender_lp1points.py -- s921.json 0.01
```

Some maps have several stage models (`scr/stage*/sNNN/*.0x1041bd9e`). Convert each one and list every OBJ after
`--merge`. Blender gets the map in metres (`--scale 0.01`) with Z up. `blender_lp1points.py` adds a
**LP1 layout** collection: one sub-collection per distinct LP1 layout, holding spawns, teams, VS, weapons and
objects. Only the first is visible.

Optional: `blender_collision.py` adds the collision as translucent coloured meshes, useful for checking that
markers sit on walkable ground.

### 3b. Install the add-on

Blender → Edit → Preferences → Add-ons → *Install from Disk* → `blender_lp2_map_markers.py`, then enable
**LP2 Map Markers**. The tools are in the 3D View sidebar (N) → **LP2 Map** tab.

Optional, to show VS, weapons and posts as their game models instead of plain shapes:

```
python3 build_marker_assets.py "PATH/TO/Lost Planet 2" markers
flatpak run org.blender.Blender -b --python blender_marker_assets.py -- markers lp2_marker_assets.blend
```

Then set the add-on's preference **Marker models** to `lp2_marker_assets.blend`.

### 3c. Place markers

- **Markers from LP1 layout**: turns the imported LP1 layouts into LP2 markers, a good starting point.
- **Variant**: LP2 maps have four layout variants (`-00` … `-03`) per game type. Markers go to
  `LP2 Layout > Variant N`, and the selected variant is the one you edit.
- **Add at 3D cursor**:
  - **FFA start**, **Team A**, **Team B**: spawn points.
  - **Team A / B base**: one each in team modes.
  - **Extra**: also used for weapon pickups when there are too few weapon markers.
  - **VS**, **Weapon**, **Data post**.
- With a marker selected:
  - its type: VS type, weapon or slot, post model
  - **Weapon mounts** (VS only, 4 slots)
  - **Tier**: 0, 10 or 20. This decides which VS / weapon amount settings make it appear; stock maps use
    roughly 45 / 33 / 22 %.
  - **Game types**: Team Elimination, Elimination, Data Post, Fugitive, Akrid Egg, Counter, VS.
- **Copy to N selected** applies the active marker's settings to the other selected ones.
- **Drop to ground** snaps the selected markers to the surface below them.
- Rotation about Z = facing direction. The panel warns when a variant has fewer than 16 FFA / team spawns
  (the game then reuses points).

**Weapon slots:** these ids pick a weapon of their class from the match settings: `0x0c` Handgun;
`0x15`–`0x19` Frag / Gum / Disk / Dummy / Plasma grenade; `0x30`–`0x34` Standard / Short / Long / Heavy /
Special. Other ids are fixed weapons.

### 3d. Export and build

**Export Layout** writes a JSON file. Build with it:

```
python3 lp1map.py --game "PATH/TO/Lost Planet 2" --lp1 lp1/nativeXenon/ZZPack2/s921.arc \
    --name "Area 921" --layout s921_layout.json Area921.zip
```

The spawn count per file stays the stock one (16 per role); spawn markers fill it in order and wrap around.
VS, weapons and data posts are exactly the markers you placed.

---

## Single tools

Each script prints its usage and the file format it handles when run without arguments (the docstring
at the top of each file).

| Tool | Does |
|---|---|
| `arcx.py` | list / extract / pack MT Framework archives (`.arc`) |
| `arcput.py` | replace entries in an archive by name |
| `arcsub.py` | same-length text substitution through an archive (resource paths) |
| `lp1model.py`, `lp1tex.py` | LP1 models / textures → OBJ / DDS |
| `lp1points.py` | LP1 multiplayer layouts → JSON |
| `lp2stage.py` | LP1 stage models → LP2 stage model |
| `lp2col.py`, `sbc.py` | collision converter / reader |
| `lp2havok.py`, `hkpack.py` | Havok physics converter / packfile reader |
| `lp2layout.py`, `objset.py` | spawns + objects writer / reader |
| `lp2light.py` | light, filters, scene box, intro camera |
| `lp2thumb.py` | map thumbnail |
| `mod2obj.py` | LP2 models → OBJ (to look at stock maps) |
| `blender_layout.py` | stock LP2 spawns / objects into a .blend, for reference |

## Known limits

- **Radar map:** stays Desecration's.
- **Music, ambient sound, water planes, effects:** stay Desecration's.
- **Lighting:** one daylight setting. It isn't fitted to each map; set `--sun` and the filter options by eye.
- **Moving parts:** LP1's moving parts and gimmicks (doors, lifts, turbines) aren't ported. The geometry
  stays where LP1's model has it.
- **Spawn counts:** fixed by the stock file (no writer for the spawn file yet).
- **Mismatched packages:** a map built differently on two PCs counts as two different maps. The host's copy
  is sent to joiners.
