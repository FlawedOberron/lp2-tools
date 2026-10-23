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

Bones and vertex groups use readable joint names: `pelvis`, `spine`, `chest`, `neck`, `head`,
`l_shoulder` / `l_upperarm` / `l_forearm` / `l_hand` / `l_fingers`, `l_thigh` / `l_shin` / `l_foot`
(and `r_` for the right; the character's left is -X), plus the stock chain bones and mounts
(`python3 lp2bones.py` prints the full table with the game's joint ids). The exporter also reads the
old `j018` style and common aliases (`UpperArm.R`, `clavicle_l`, `LeftCalf`, `hips`...), so rigs from other
tools can keep their names. Older .blend files: `flatpak run org.blender.Blender -b FILE.blend --python
lp2_skeleton.py -- rename` (importing into an old rig renames it too).

`skeleton/lp2_skeleton.blend` is the bare skeleton (armature `LP2_rig`, every standard joint at the game's
bind pose) for rigging a new model from scratch: parent your mesh to it and weight to those bones.

A part can only use the joints its template has; the exporter stops with a list if you weight to anything
else. Influences under 0.002 are dropped.

## 5. Custom bones (hair, cloth, gear)

- Any bone that isn't a standard joint name (or alias) is custom. Name it what you like.
- It must hang off a joint the part already has (hair off `head`), either directly
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

## 8b. Materials (including glowing and animated ones)

Every mesh piece uses one **material of the template part** (the original rModel the set is built
on). You can't add new materials yet; you pick which of the template's materials each face uses.

- The importer names materials `<part>_mat000`, `<part>_mat001`, ... and tags each with the custom
  property `lp2_mat` (its index in the template). **Keep these materials** on your new geometry.
  Assign them per face (material slots) like any Blender material; the exporter writes one mesh per
  material in use.
- To use a material on new faces: add the imported material to the object's slots and assign the
  faces. A material you made yourself is accepted if it has an `lp2_mat` custom property (template
  material index) or a name ending in `_matNNN`.
- Without either, the faces get the template's first textured material, which is often the
  wrong one (on the 29xx backpack that is the **emissive** material: the part showed only its glow).
- **Glow and animation belong to the material, not to the texture or the mesh.** Some template
  materials are emissive (they light up), and some of those animate their glow (pulsing or
  scrolling light strips, e.g. on the 29xx backpack). Any face you put on such a material glows and
  animates the same way. Use this deliberately for lights and screens, and keep ordinary surfaces on
  the plain materials.
- To see which material is which: in the import, select a material and look at what it covers on
  the original part (light strips, visors and screens are usually the emissive ones). A list of the
  emissive / animated materials per template part is planned.
- The shadow copies use the template's untextured material automatically; you don't assign that.

## 9. Colour variants (the four "shaders") and textures

### What the four options are

Every stock part has up to four **colour variants**, the A / B / C / D swatch next to the part in
the customisation menu. They are not separate shaders: each is a **different colour map texture**
(`<part>_BM-00_A` … `_D`) laid over the same model, normal map and mask. The artists painted the
skin areas identically in all four and changed the cloth, which is why the clothes recolour and
the skin stays the same.

### Choosing a custom part's colours (works now, DX9 and DX11)

List the colours a set offers in `lpc.json`, in menu order:

```json
{ "id": "scav01", "name": "Scavenger", "faction": "FF", "colours": "ACD", "parts": { ... } }
```

`"colours"` is a string (`"ABCD"`) or a list (`["A", "C"]`) of letters `A`–`D`.
- **One colour** (`"C"`): the swatch stays locked, like a stock single-colour part.
- **Two to four:** the swatch arrows show and step through just those letters (the swatch picture
  stays the "LOST PLANET 2" placeholder; the letter shows next to it).
- A newly picked part starts on A if listed, else on the first letter.
- The old `"colour": "B"` still works and means that one colour only.
- The Blender exporter writes `"colours"`: the set root collection's custom property
  `lpc_colours` (e.g. `ACD`) if set, else A plus every letter a part has its own colour map for.

Which texture each letter wears, per part: the part's own `_<letter>` colour map if it has one,
else its own `_A` (a retextured part's UVs don't fit the template's colours), else the template
part's colour map for that letter.

The player's choice is remembered per set and part in `ModCache\parts\colours.txt` (the game's
save keeps one id for a DLC part, with no room for its colour). Per-loadout colours come with the
carrier system.

Notes:
- The fallback variants are the **template part's** (the stock part your set is built on, e.g.
  bd2900). To wear another part's colours, build on that part as the template.

### Custom textures (works now)

A part can wear its own textures instead of the template's. Add **Image Texture** nodes to the
part's materials (any material of the part) with images named by role:

| Image name ends in | Role | Notes |
|---|---|---|
| `_A` (`_B`, `_C`, `_D`) | colour map | the four colour variants (menu letters in `lpc.json "colours"`); a missing letter falls back to `_A` |
| `_NM` | normal map | ordinary tangent-space normal map (Blender / OpenGL style, Y up); the exporter converts it to the game's layout |
| `_MM` | shininess mask | greyscale: white shiny, black matt (see below) |
| `_MM_B` (`_MM_A`.. `_MM_D`) | one colour's shininess mask | that colour wears it; the others keep `_MM` (see "Shine per colour") |
| `_NM_B` (`_NM_A`.. `_NM_D`) | one colour's normal map | e.g. a smooth latex colour and a textured one |

E.g. `scav_body_A.png`, `scav_body_NM.png`. The exporter encodes them (DXT, with mipmaps) as
`<part>_<role>.rTexture` next to the models and lists them in `lpc.json`. Anything you don't
provide stays the template's.

- **Size:** powers of two; stock parts use 512 x 512 for colour and normal maps (bigger costs
  memory and download size, see §10). Other sizes are scaled up to the next power of two.
- **UVs:** the template's layout is the safe start: paint over the template's texture
  (extracted under `lp2-assets/raw/...`), keeping its islands, especially when you keep template
  geometry. New geometry can use free areas of the sheet.
- **Skin:** keep skin areas consistent between `_A`.. `_D` (stock parts only recolour cloth).
- **Shininess (`_MM`):** the game's specular mask, greyscale. Most stock parts use one flat grey
  (uniform shine); a few paint it: set 29's face (skin shine), bd2000's chain links (bright on matt
  cloth), some visors and metal. Mid grey (about 100/255) matches the stock look.
- **Glow** is not a texture: it comes from the material (§8b).
- One file by hand: `lp2tex.py IN.png OUT.rTexture --kind bm|nm|mm`.

Planned: a skin-tone tool (a skin mask plus HSV sliders that generates the `_A`..`_D` variants
with skin and cloth recoloured separately).

### Shine per colour (works now, confirmed in game 2026-10-18)

Stock parts share one mask and one set of material values across all four colours. A custom part
can give each colour its own: the loader builds a model copy for every colour that changes
something and loads it with that colour. Three controls, strongest first:

| Control | Where | Effect |
|---|---|---|
| mask map (`_MM` / `_MM_<letter>`) | texture | **specular strength** per area: white full shine, black none. Stock is about 52 % grey |
| `spec_colour` | material | specular colour multiplier, one number or `[r, g, b]` (stock 1.0; 0 = no highlight, 3-4 = very glossy) |
| `spec_power` | material | **highlight size**: low (4-8) broad sheen, high (50+) small pinpoint (a tiny highlight reads as *less* shiny). Stock 6-50 per material |

Material values go in `lpc.json`, per part, per colour, per material (`"*"` = every lit material,
or the material's index from the import):

```json
"body": {
  "file": "body.rModel", "template": "bd2900.rModel",
  "textures": {"BM_A": "body_BM_A.rTexture", "MM_B": "body_MM_white.rTexture", "MM_D": "body_MM_dark.rTexture"},
  "material_overrides": {
    "B": {"*": {"spec_power": 24, "spec_colour": 3.5}},
    "D": {"*": {"spec_power": 4, "spec_colour": 0.3}}
  }
}
```

Tested on bd2900's skin: **latex** = white mask, `spec_power` 24, `spec_colour` 3.5 (really
shiny); **neoprene** = 16 % grey mask, `spec_power` 4, `spec_colour` 0.3 (really matte).

**In Blender.** The importer sets each material up like the game draws it: colour map -> Base
Color, normal map -> Normal Map node -> Normal (the game's channel layout converted by nodes),
shine mask -> Specular IOR Level, and **Roughness** from the material's `spec_power` (Blinn-Phong
power p <-> roughness r: p = 2/r^4 - 2; stock 6-50 = roughness 0.71-0.44). Each material also gets
`lp2_spec_power` / `lp2_spec_colour` custom properties holding the stock values. The exporter:

| You change | Exported as |
|---|---|
| a material's Roughness slider (not driven by a texture) | that material's `spec_power`, every colour |
| its custom property `lp2_spec_colour` | that material's `spec_colour`, every colour |
| custom property `lp2_spec_power_B` / `lp2_spec_colour_B` (any letter) | `material_overrides` for that colour in `lpc.json` |
| images ending `_MM_B` / `_NM_B` | that colour's own mask / normal map |

Unchanged materials export byte-identical to the template. `spec_power` is one number per
material (the game's shaders have no per-pixel highlight-size map; a painted Roughness texture
is not exported); for areas that need different highlight sizes, put them on different
materials. Blender's preview is a PBR approximation of the game's older specular lighting:
judge shine in game. Note low roughness (high power) gives a small pinpoint highlight, which in
LP2 reads *less* shiny unless the mask and `spec_colour` are strong. For research, a raw material word also works as a key (`"19": 0.2`:
the float at that 4-byte index of the 160-byte material record; 19 and 16-17 are still unknown).

### How the game stores it (reference)

| Archive | Contents |
|---|---|
| `bd2900.arc` | model, normal map `NM-00`, mask map `MM-00`, effects, sounds |
| `bd290000.arc` … `bd290003.arc` | one colour map each: `BM-00_A` … `_D` |

Formats: colour DXT1 (19), normal map DXT5 with X in alpha and Y in green (31), mask DXT1 (25).

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
