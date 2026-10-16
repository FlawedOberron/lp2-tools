# Lost Planet 2 custom parts: Blender → game

Tools in this folder:

| Script | What it does |
|---|---|
| `lp2_blender_import.py` | Game `.rModel` parts → Blender (rig, weights, UVs, normals, textures, LOD collections) |
| `lp2_blender_export.py` | Blender `LPC_…` collections → `.rModel` parts + `lpc.json` |
| `lp2model.py` | The model writer both of the above rely on (no Blender needed) |
| `test_lp2model.py` | Rebuilds shipped parts through the writer and checks they decode the same |

**Status:** the exporter's output re-imports correctly and rebuilds the game's own parts accurately,
but it has **not been tested in-game yet** (that needs packaging, next step). Materials and
textures are not authored yet: exported parts reuse their template's.

---

## 1. Start from a reference

Import the original parts you are replacing (or open a ready-made file, e.g.
`~/Projects/lp2-assets/characters/femme_fatale/ff_set29_00.blend`):

```
flatpak run org.blender.Blender -b --python lp2_blender_import.py -- OUT.blend hd.rModel bd.rModel lg.rModel bk.rModel
```

You get one armature, `LP2_rig`, and three collections, `LOD Hi`, `LOD Med` and `LOD Lo`, one
part each. Only Hi is visible; toggle the eye icons to compare levels. Model against **Hi**.

Every faction shares the **same core skeleton**. Joints j000-j019 and j101 sit in identical
places in all 143 shipped parts, Femmes Fatales included, so a part built on one character fits
all of them. The only differences are:
- `j020` / `j021` (hand ends) sit up to 9.5 cm further out in the bd21xx / bd26xx sets.
- Joints 30-49 and 100 are per-part helpers (pouches, packs, cloth). The same number means
  different things in different parts, so don't weight generic parts to them.

## 2. Scene layout

```
LPC_<id>_<faction>_<display name>        e.g.  LPC_scav01_ALL_Scavenger Kit
├─ body
│   ├─ torso
│   ├─ belt
│   ├─ hand_grip
│   └─ hand_open …
├─ head
├─ back
└─ legs
```

- **`<id>`**: letters and digits only. It must be unique per set and is only used for folders and
  packaging (the packer assigns the game's internal slot names).
- **`<faction>`**: one of the codes below.
- **`<display name>`**: the menu name. Spaces are fine, up to 43 bytes. Plain ASCII is safest;
  other characters haven't been checked against the game's font.
- Part collections: `body`, `head`, `back`, `legs`. Case doesn't matter and Blender's `.001`
  suffixes are ignored, so every set can have its own `body`. You don't need all four; empty or
  missing parts are skipped.
- Several `LPC_` sets in one scene are fine; each exports separately.
- Objects hidden from render (camera icon) are not exported, which is handy for reference meshes.

### Faction codes

| Code | Faction | Game value |
|---|---|---|
| `RND` | Rounders | 0 |
| `FJ` | Fight Junkies | 1 |
| `SPE` | Snow Pirate Elites | 2 |
| `NEV` | NEVEC Black Ops | 3 |
| `FF` | Femmes Fatales | 4 |
| `ALL` | Generic, offered to every faction | none |

(The faction is recorded in `lpc.json` for the packer. The DLC menu currently shows DLC parts to
every faction; applying the restriction is packer and DLL work still to do.)

### Object names

| Name | Meaning |
|---|---|
| anything (`belt`, `bandolier`) | Always shown (part group 0). The name is just a label. |
| `<name>_g<NN>` | Explicit part group NN (groups 1-17 are probably hidden when other parts would clip; unconfirmed) |
| `hand_<pose>` | A hand pose (below). The side is worked out from which side of the body it's on. |

Custom property `lp2_group` on an object overrides all of the above.

### Hand poses

The game swaps whole hand meshes instead of bending fingers. Make one object per pose:

| Name | Shape | Hands |
|---|---|---|
| `hand_grip` | fingers curled round a handle | both |
| `hand_open` | flat hand | both |
| `hand_fist` | closed fist | +X hand only |
| `hand_point` | index finger out | +X hand only |
| `hand_peace` | index + middle out | +X hand only |
| `hand_thumb` | thumbs-up | +X hand only |

Reference renders: `~/Projects/lp2-assets/previews/hand_poses_bd2900.png`.

## 3. Modelling rules

- **Model only the high detail level.** The exporter flags everything for every distance and makes
  the shadow copies itself.
- **Shade smooth.** Flat shading splits every face corner into its own vertex, roughly tripling
  the count. Hard edges and UV seams are fine where you want them.
- **Don't split meshes for the game.** The exporter splits by material and keeps pieces under
  65,535 vertices. Only split where the game needs a separate piece: hand poses and part groups.
- Vertex counts: Viewport Overlays → **Statistics**. The game's count ends up somewhat higher
  (seams and hard edges duplicate vertices); `export_report.txt` has the real numbers.
- Budget: originals are about 1,100-1,900 vertices per part. Under about 10k per part with 1-2K
  textures is safe. Texture memory matters more than polygons (the game is 32-bit).

## 4. Skinning

1. Parent the mesh to `LP2_rig` (an Armature modifier).
2. Copy weights from the original part. Robust Weight Transfer (free, extensions.blender.org)
   or the Data Transfer modifier works well.
3. Clean up in Weight Paint, then **Weights → Limit Total (4)** and **Normalize All**.
4. Test in Pose mode (bend the arms, legs and spine), then clear the pose with Alt+G / Alt+R.

Vertex groups keep the game's joint names (`j018` …). A part can only use the joints its
template has; the exporter stops with a list if you weight to anything else. Influences under
0.002 are dropped.

## 5. Custom bones (hair, cloth, gear)

- Any bone **not** named `jNNN` is custom. Name it what you like.
- It must hang off a joint the part already has (hair off `j011`, the head bone), either directly
  or through other custom bones. Chains and branches are fine.
- **Only bones carrying weight are exported**, plus any unweighted bones linking them to the
  skeleton. Spare bones are listed in the report and skipped.
- Each custom bone gets a joint ID the first time it's exported (from 254 downward). The ID is
  stored on the bone as `lp2_joint` so it never changes. The physics files will refer to it later.
- Limits: 100 custom bones per armature (hard). Above **31 bones in total per part** you get a
  warning: no shipped model has more, and the game's skinning may not handle it. To be tested.
- Physics (swing, bounciness): not yet. Custom bones currently just follow their parent rigidly.

## 6. Templates

Each part is written on top of an original game part, its *template*. The template supplies the
standard skeleton, materials and textures. It's chosen in this order:

1. Custom property `lp2_template` (path to an `.rModel`) on the part collection or the `LPC_` collection.
2. The original part of that slot imported into the same `.blend`.
3. The 29xx (Femmes Fatales) part, with a warning.

Since the core skeleton is the same everywhere, the template mainly decides which helper joints
(30-49, 100) and which materials you get.

Materials: custom property `lp2_mat` (template material index) on an object or its material,
otherwise the template's first textured material.

## 7. Export

- **In Blender:** open `lp2_blender_export.py` in the Text Editor and click Run Script. Output goes
  to `lp2_export/` next to the `.blend`.
- **Terminal:** `flatpak run org.blender.Blender -b FILE.blend --python lp2_blender_export.py -- OUTDIR [set names…]`

Output:

```
OUTDIR/
  export_report.txt          vertices, triangles, bones, custom joint ids, warnings
  LPC_<id>/
    body.rModel  head.rModel  back.rModel  legs.rModel
    lpc.json                 id, display name, faction, per-part template + custom joints
```

## 8. Hitboxes

Hitboxes don't come from your model. Every human uses one shared file,
`collision\hm\human.rHit` (in `aPowerOn.arc`): 21 spheres and capsules attached to skeleton
joints with fixed radii. For example:

| Shape | Joints | Radius |
|---|---|---|
| Head sphere | j011 (raised ~6 cm) | ~14 cm |
| Upper arm | j013-j014 / j017-j018 | 7 cm |
| Forearm | j014-j015 / j018-j019 | 8 cm |
| Thigh | j002-j003 | 15 cm |
| Shin | j003-j004 | 10 cm |

(Only some of the 21 shapes are decoded so far.)

- Custom parts can't change hit size, so they can't be used to cheat.
- Bulky armour that sticks well outside these shapes looks hittable where it isn't, and very slim
  models seem to absorb near-misses. Staying near the original silhouette avoids that.
- Custom bones (hair, capes, tails) have no hitboxes.
- Changing hitboxes means replacing the shared file for everyone, identically on all players.

## 9. Textures and skins (planned, not built yet)

How the game does it (e.g. bd2900):

| Archive | Contents |
|---|---|
| `bd2900.arc` | model, normal map `NM-00`, mask map `MM-00`, effects, sounds |
| `bd290000.arc` … `bd290003.arc` | one colour map each: `BM-00_A` … `_D` |

A skin is just another colour map; the shape, normal map and mask are shared. Up to 4 per part.

Planned authoring:
- **Colour map:** connect it in the material as usual, named `<name>_A.png`. Extra skins go next
  to it as `<name>_B.png`, `_C`, `_D`; the exporter picks up whichever exist.
- **Normal map:** `<name>_NM.png`. **Mask (optional):** `<name>_MM.png`. Both are shared by all skins.
- **Skin-tone mask (later):** `<part>_SKIN.png`, greyscale, white = skin. Used to generate
  tinted colour variants.
- **Reusing a game texture:** point the material at an extracted game texture under
  `lp2-assets/raw/…` (e.g. `raw/CustomParts/bd2900/model/hm/hm29/bd2900/bd2900_NM-00.dds`). The
  exporter writes the game's path into the model and ships nothing for it.

To be confirmed in-game first: whether a part can load a texture that lives in another part's
archive (if not, the DLL serves it), and how the variant letter is picked.

## 10. Size budget: everything must be sendable

Custom parts and maps will be transferred to other players over the in-game (Steam) networking,
and everything has to fit in a 32-bit game holding 16 characters (more if the player cap is
raised later). Smaller is better:

- **Textures dominate.** A 1K colour, normal and mask set is roughly 1.5-3 MB per part, and each
  extra skin adds 0.2-1 MB. Models are about 0.3-0.6 MB per part before compression.
- **Reuse game textures** where you can; they cost nothing to send.
- Prefer 512² colour maps for skins; keep 1K for things seen up close.

| Content | Rough target (compressed) |
|---|---|
| Part set (all four parts) | under 2-4 MB |
| Map | under 20-30 MB |

These are first guesses until real transfer tests. Planned delivery: content is identified by
hash and cached, it downloads in the lobby before the match, and anyone still missing it sees a
fallback part.

### Memory: turn on Large Address Aware (LAA), use DX11

LP2 is a 32-bit program. By default it can address only **2 GB**; its exe doesn't set the
Large Address Aware flag. With LAA it gets **4 GB** on a 64-bit system, which is a lot of
headroom for custom content and a raised player cap. (Going truly 64-bit would need Capcom's
source code.)

**Steam launch option (Proton), no exe changes:**

```
WINE_LARGE_ADDRESS_AWARE=1 %command%
```

(Steam → Lost Planet 2 → Properties → Launch Options.) Unlike patching the exe header, this
survives Steam updates and "verify files" and doesn't touch the SteamStub-wrapped exe. Still to
check in a running game: that it actually took effect (the process should reach past 2 GB),
and that LP2 has no problems with LAA (rare, but a few old games misuse the top address bit).

**The limit is address space, not RAM or VRAM.** Graphics memory counts against it depending on
the renderer:

| Exe | Textures |
|---|---|
| `LP2DX9.exe` | Usually a copy in VRAM **and** one inside the game's 4 GB, so they count twice |
| `LP2DX11.exe` | Mostly in VRAM only; just temporary upload buffers use address space |

**Use the DX11 exe** with custom content (the DLL mods also target DX11). Everyone in a match
needs LAA too for the extra room to help, so bundle it with the mod setup if the player cap goes up.

**Maps, for reference:** ONLINE_00 is about 184k triangles in 61 pieces. Aim for 150-300k
triangles and keep the piece count similar (each piece is a draw call). Keep collision low-poly
(low tens of thousands of triangles).

## 11. Distribution

The player-facing guide (install, folder layout, settings, map/part/mod packages, what a release
may and may not contain) is `docs/LP2-MODS.md` in the DLL repo
(`~/Projects/xlive-steamworks-src`).

For creators:
- A part set ships as its exported `LPC_<id>` folder (or that folder zipped) for the game's
  `Parts\` folder. Don't ship your `.blend` or extracted game files with it.
- Ship only new content. Textures taken from the game go in by reference (section 9), never as
  copies.
- Check `export_report.txt` against the size budget (section 10) before sharing.
- This creator kit (the scripts here and this README) is a separate download from the player
  release.
- Planned public release: once parts and maps load in game and multiplayer picks them up. That
  is also the point to approach sokie about upstream or per-game builds.

## Not done yet

1. Packaging an export into a DLC package (`lp2pack.py` / `dlcpart.py`) and the first in-game test.
2. Textures and materials (section 9).
3. The custom part loader: unlimited parts through one carrier slot per category (started in the DLL as `src/mods/parts.cpp`).
4. `.rChain` physics for custom bones.
5. Confirming what part groups 1-17 do, and which side +X is in-game.
6. Network transfer of parts and maps.
