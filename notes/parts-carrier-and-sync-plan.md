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

### Reverse engineering needed
- FUN_00f664b0: arguments (does it see which player/character it builds for?), path formats and
  which name lengths are fixed; how the resource cache keys entries.
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
