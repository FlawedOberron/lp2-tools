# Plan: carrier parts (unlimited + A–D colours) and multiplayer sync

Status 2026-10-17: custom parts work through generated DLC packages (xlive `mods/parts.cpp`):
one DLC slot (20-69) per set, colour fixed per set (`lpc.json "colour"`), unlocked in the
profile by a thread. This plan replaces the slot limit and the fixed colour, then makes parts and
maps work between players.

---

## 4. Carrier system

### Goal
- Any number of custom sets per category, not 50.
- Players pick a custom part's colour A–D in the menu like a stock part.
- No content packages or DLC slots; Capcom's DLC slots stay free.
- Each player's choice is independent and travels with their character (needed for sync).

### Design
1. **One carrier id per category.** Reserve one part id per category (candidates: a DLC id such as
   249, already in every category list and unlockable, or an id the menus can be made to list).
   Every custom part is worn *as* the carrier; which custom part it is lives in our own data.
2. **Menu.** In the parts menu, Left/Right on the carrier steps through the registry (filtered by
   the menu's faction, menu+0x124) instead of moving on; the name shown is the set's name; the
   colour swatch cycles A–D as for stock parts.
3. **Choice storage.** A side table next to the game save
   (`Documents\capcom\LOST PLANET 2\<gamertag>\lp2mods-parts.json`): per loadout slot and category
   → set content hash + colour. The game save only ever holds the carrier id, so removing the mod
   leaves a valid save (the carrier shows as its stock part).
4. **Loading.** Hook the part path builder (DX11 FUN_00f664b0): for the carrier, return a path
   unique to the wearer's set + colour (so two players in different custom parts never share a
   cached resource), and serve the files from ModCache through the overlay (the archives the
   generator builds today, renamed to that path).
5. **Fallback.** A player whose set is missing locally renders the template's stock part.

### RE findings (2026-10-17, DX11)
- **FUN_00f664b0** `thiscall(parts, char* out, int kind, uint cat)`: builds a resource path with
  sprintf. `parts` = a character's parts object: per category `cat` 0-3 (4 = an om7118 prop) the
  bytes at +0x44+cat*4 = set, +0x45 = colour (0-3 -> 'A'+c), +0x46 = variant; +4 = the
  character's unit (byte +0x1f = unit category), +10 a flag. `kind`: 0 model, 1 colour texture
  (`_BM-00_<c>`), 2 sound, 3 effect provider, 4/5 extra models. Formats:
  normal `model\hm\hm%02x\%s%02x%02x\%s%02x%02x` (+ `_BM-00_%c`); DLC (set & 0xdf == 0x0e)
  `model\hm\hmf6\%sf6%02x\...` always colour A; set 0x2c -> hmf4/5/7 specials, 0x2d -> hmff;
  FUN_00f5e4e0(cat) true -> hmf2 placeholder ("none").
- **FUN_00f66c30** (only caller): 64-byte buffer, then the resource manager
  `(*(*0x18d0ccc) + 0x2c)(type, path, 1)` with type rModel 0x18e16d0, rTexture 0x18e16b0, sounds
  0x18c7cd0, effect providers 0x18c6dd0. MT loads a resource as a loose file under nativePC\ when
  no archive has it (already used for map boot files), so **the carrier can return any path (< 64
  chars) and serve loose files from ModCache via the overlay**: no DLC packages, no slot limit, no
  same-length renames (texture names in a model sit in fixed 64-byte records).
- The parts object knows its character (+4), so per-player choices (local side table now, synced
  member data later) can decide the path.

### Reverse engineering needed
- ~~FUN_00f664b0 arguments and path formats~~ (done, above). Still: how the resource cache keys
  entries (path + type, presumably), and where the parts object's bytes are filled from (menu /
  save loadout / network member data).
- Parts menu (DX9 FUN_00ed4ca0, DX11 equivalent): list building, L/R handling, the name and colour
  swatch drawing (Flash calls, like the key config menu).
- Where a character's part ids and colours live at runtime and in the save (s1 loadouts) and how
  they are sent to other players in a match (session / member data).
- Whether the carrier needs its own unlock bit only (likely, via the existing unlocker).

### Steps
1. RE the path builder + menu; prove one carrier in one category showing two different custom
   sets on two characters (offline).
2. Menu cycling + names + colour; side table.
3. Serve per-set archives by unique path; drop the DLC package route (keep it as a fallback switch
   for one release).

---

## 5. Multiplayer sync (parts and maps)

### Problem
Everyone in a match needs (a) the same content and (b) the same meaning for every id.
Today: parts use deterministic slot order but differ if players' Parts folders differ; maps need
the same Maps\ zip.

### Where it lives (user decision 2026-10-17)
The transport is **core xlive.dll**, not a plugin: maps and parts both use it, and joining a match
depends on it. Plugin mods (Controls, SkipSplash, DevTools, future DLL mods) are client-side: they
are never synced, advertised or sent over the network, and a match never requires them.

### Design
1. **Identify content by hash.** Every set / map package gets a content hash (of its zip or its
   files). The loader caches by hash in `ModCache\content\<hash>\`.
2. **Advertise.** Through the Steam lobby (xlive-steamworks sessions are Steam lobbies):
   - lobby data: the match's map package hash (+ name, size);
   - member data: each player's worn custom parts (category, set hash, colour) — with the carrier
     system this replaces slot numbers entirely.
3. **Fetch.** Missing hashes are downloaded peer-to-peer over Steam networking
   (SteamNetworkingMessages), chunked, from the host or the player wearing the part; verified by
   hash, then unpacked and indexed like local content. Budgets (README-parts §10): part set a few
   MB, map tens of MB.
4. **Until it arrives.** Parts: fallback stock part, swapped in when ready (carrier makes this live).
   Maps: the player waits in the lobby (or can't ready up) until the map is present; host may set
   "mods required" per match.
5. **Safety.** Data only, never code (no plugin DLLs over the network); size limits, zip and
   rModel parsing hardened against bad input, hash checked before use; a setting to turn
   downloads off (then mismatched players see fallbacks / can't join modded maps).

### Steps
1. Content hashes + hash-addressed cache for local Parts\ and Maps\.
2. Lobby/member metadata publish + read (no transfer): log mismatches, show fallback.
3. P2P transfer with resume/verify; UI hint (Steam overlay toast or in-game message).
4. Maps: block ready-up until present.

### Order of work
Carrier first (it removes slot numbers, which makes per-player sync simple), then sync steps 1-4.
Contact sokie (upstream xlive-steamworks) once parts + maps load and sync (user's call).

## 6. Sync groundwork: per-character carrier (RE 2026-10-18, DX11 addresses)
Today every lookup goes by (category, alias slot): a remote player on the same faction/loadout
alias as ours would show OUR set. The receiving side must resolve per character.
- Archive request `FUN_007d3fd0(character, cat, code)` (via 7d41f0 / 7d4260 / 7d4350): sprintf
  `CustomParts\<pfx>%02x%02x%02x` (colour) and `CustomParts\<pfx>%02x%02x`; DLC (f5c7f0(code)) ->
  `7d05e0(cat, code)` (package) -> `7d3c30(character, cat<<8|variant, "arcXmlTmpPC", name, 4, 2, 2)`;
  else `7d2700(character, "arcXmlTmpPC", name, 0, 2)`.
- Release `FUN_007d29b0(loader, character, cat, code)`: same names from the code -> `7d18b0(name)`
  (frees by name from a 0x60-entry table, entry 0x4c: +4 resource, +8 name[64]).
- Loader character slots: 0-31 at loader + i*0x1ca8 (flags +0x1ca4 bit 4 = in use).
- Path builder FUN_00f664b0: parts+4 = unit; unit+0x1f (1-8) looks like the player slot (kinds
  4/5 test it); unit+0xcd0 some state (6 / 0 skip).
Plan:
1. Per-character set table: (character or player slot, category) -> set; local player from our
   choice, remote from lobby member data, debug override from config (fake player / bots).
2. Hook 7d3fd0 + 7d29b0 for carrier codes: name = the set's token (`CustomParts\bdzkqm`, colour
   `bdzkqm<cc>`), remembered per (character, category) so the release frees what was requested;
   overlay maps `...\customparts\<token>[cc].arc` to the set's build (any root).
3. PartPath: the character's set (map parts/unit -> character; check unit+0x1f against loader slot).
4. Debug "fake player": config {"debug_carrier": {"slot": N, "body": "spe3"}} forcing a bot's or a
   slot's carrier set, to test without a second client. Bots wear stock codes, so forcing them also
   needs their code swapped to a carrier code at request + path time.
Open: what is `character` for the menu preview vs. players vs. bots; is unit+0x1f the same index.

## 7. Ideas to build later (user, 2026-10-18)
- **Mod manager screen**: in-game (or launcher) screen listing mods (part sets, maps, plugins)
  with on/off toggles and a config editor per mod (e.g. plugin json, lpc.json colours/faction).
  Needs: a per-mod enabled flag the loader honours (Parts\, Maps\, plugins), and a UI host
  (in-game Flash page via the menu hooks, or an overlay window).
- **Opt out of synced parts**: a setting so a player never downloads other players' part sets.
  Remote players wearing a set we don't have (or won't fetch) then show the faction's first stock
  set for that category (the faction's default part), not the carrier. Default: sync on.
  Fits §5 step 4 (fallback until it arrives) with "never arrives" when opted out.
