# Two-player test 2026-10-21: bugs (user's list) + first triage

## Next session (user's picks, in this order)
1. **Save:** use Gato's save as the reference.
   - It's 90-91 % content complete, so a better test file for everything we'd need.
   - Written by an older, backdated LP2 build that he kept to keep his save. So it's an older save
     format: decode it and convert or import it.
   - Discord's transfer trimmed the name to `...Save-`.
2. **[DL - X/X] not showing for other users.**
   - Everyone ran the same DLL build.
   - The user always sent (custom parts and maps). The others had none, so they only ever received.
   - The user saw the receivers' [DL] progress, but the receivers never saw their own.
   - So the label probably shows only other members' `content` member data. The local player's own
     download state (TransferProgress) never reaches their own lobby row: own member data isn't read
     back, or isn't echoed by Steam before the transfer ends.
   - Check where the lobby UI picks the [DL] text, and use the local transfer state for your own row.
3. **"Digs" on Battlegrounds** = "dig here" piles with buried items, in odd places: almost certainly
   Desecration leftovers.
   - Find the group / record kind in rObjSet (the Common file or the per-mode files).
   - lp2layout should drop them, as it does the Common gimmicks.
4. **Spacewar (480) network layer** for the many non-Steam copies that want to join: helper process on
   480 + a `"non_steam"` option.

Later: mystery meatsuit (2), Elimination HUD online (3), leaderboards (4).

Overall: the test went very well. The game-folder log was overwritten by a later solo launch (20:39-20:46),
so nothing from the test itself survives. Next test: copy `xlive_steamworks.log` from both PCs right after
the session.

1. **Save not transferring properly (Gato's save).** The file he sent is `~/Downloads/Lostplanet2.Lostplanet2Save-`.
   - The name has lost its `capcom` suffix (likely the chat upload). The game only reads `...Save-capcom`.
   - The file isn't in the format `lp2save.py` knows: 20872 bytes versus our 20512. It starts
     `28 01 00 00 02 03 01 00 ...` and has no SHA-1 + `28 c9 ce 77` magic header.
   - Find out which build wrote it: a GFWL-era save, a newer Steam/Capcom build, or another platform.
     Then teach the import (saves.cpp) to convert it, or tell the user why it's refused.
2. **Me showing up as "mystery meatsuit" (to the other player).** My custom parts didn't reach or apply
   on his side, so he saw the placeholder / default model.
   - Check the parts transfer (member data `parts`, TransferFetch) and the carrier-slot binding on the
     joiner.
   - Needs both logs.
3. **Survival life-count HUD not showing in Elimination (FFA).**
   - The "N Respawns / Last Life" list labels were confirmed solo against bots.
   - Online it didn't show. Suspects:
     - The joiner never sees `g_survival` (rules from the host's member data).
     - The list draw hook (`ec4df0` / `ed4c00`) uses a different path when online.
4. **Leaderboards not working (sokie's original DLL too).**
   - XUserReadStats / XUserWriteStats are mapped to Steam leaderboards upstream.
   - spa: 63 stats views, 9 queries. Check which calls the game makes and what Steam returns. The
     leaderboards may not exist for app 45750 (create on first write?).
5. **Random digs on Battlegrounds:** "dig here" piles with buried items (see above).
6. **App ID 480 (Spacewar) for questionable copies.** Already planned:
   - a helper process on 480 for Steam copies
   - a `"non_steam"` config option, for players without LP2 on Steam
7. **DL not showing on clients:** see the top list. Receivers don't see their own download.

## 2026-10-22 (user)
8. **Secondary rule only on the first spawn.** Rules Spawn hook only filled slot 7 when it was empty; on respawn it
   still holds what the player carried. Fixed (untested): slot 7 = secondary on every local spawn, log shows
   "spawns with secondary ... (slot held ...)" so the respawn path is confirmed.
9. **Custom maps: green lighting and ash "snow".** Packages keep Desecration's area resources lp1map doesn't replace:
   - Ash: tool\scheduler\Effect\aArea_ONLINE_00_Efc0_360 (PlanetEffectVFR weather: mpEffectList ->
     online00_fallout / _fs1-6, rain_rate, mWaterExist / mWaterHeight, also lensf, HemiSphereLight). Not touched by
     lp2light. Fix: lp1map neutralises it (no weather effect lists, rain 0, no water) or empties the fallout lists.
   - Green: lp2light keeps the filter's ColorCorrectFilter tone curves (kind 14, not dumped yet), corrector factors,
     bloom / sky. Also still Desecration's: sa\DX9|DX11\...\Area_ONLINE_00\package.arc, detail .tde, EnvMap cubemaps,
     MaterialSkipList. Check: dump the curves, compare a screenshot; trace_opens on a custom-map load for the full list.
   - 2026-10-22 ash/water: lp2light.effects() zeroes mWeatherRate (online00: 50) + mWaterExist in *_Efc*
     schedulers; lp1map passes them. Area921.zip + Battlegrounds.zip patched in place (arcput), installed; originals
     in lp2-assets/maps/pre-fxfix/. UNTESTED. Note: Weather rule in Create Match may still override mWeatherRate.
10. **Deep snow (idea for custom maps).** Ground materials in the exe (DX9 strings ~0xf5f3xx-0xf5f4fc): ... GAREKI,
    JUNGLE, BINIIRU, TOTAN, TAINAI, MOKUZOU, NET_MUD, NET_GRASS, WATER_INSIDE, HAVOK_FENCE, LAVA, BRICK,
    SAND_MIX_ROCK, SOIL, WOOD, WATER, ICE, SNOW, GLASS, NET_SAND, METAL, CONCRETE, DEEP_SNOW. Likely the collision
    surface's material (lp2col/sbc surface flags 0x8000xxxx material bits) -> sinking. Confirm on a snowy campaign
    area's rCollision (surface flag values vs this list); then lp2col / Blender can tag DEEP_SNOW faces.
11. **Water for custom maps (user: LP1 maps with water / underwater areas).** Water = one plane per area in the Efc
    scheduler: mWaterExist + mWaterHeight (cm). Stock: 00/06/11 h 0, 05 h -230, 01 -500000 / 03 -50000 (= none),
    08 +500000 (all underwater), 07/09/10/12/15 none. Visuals in the area arc (online00: o00water / o00water2 rModel,
    on00_suimen rSwingModel, on00_water rScheduler, online_water rEffect2D, area4_UnderWater0, MT_Water, In_Water_amb).
    Plan: map setting "water": height -> mWaterExist 1 + height (absent = off, as now); visible surface mesh with a stock
    water material (Blender plane or flat plane at the level); collision faces tagged WATER (cf. DEEP_SNOW, 10).
    One level per area (multi-level LP1 maps: compromise or find a per-zone setting). lp2light.tracks fails on
    online 02 / 04 Efc schedulers (string table) - fix.
12. **Map volumes (user, map builder).** One volume system for custom maps: boxes (later convex shapes) placed in
    Blender / the map builder, exported with the layout, each with a type: kill, damage (rate), T-ENG refill (rate),
    water (you count as underwater inside it). The DLL tests the players against them (host decides kills / damage
    online). Water volumes: find where the game compares a position with mWaterHeight (player swim / underwater
    state, camera underwater filter, effects) and hook it so a volume answers "underwater" with its top as the
    surface. Then more than one water level per map works too (11).
   - 2026-10-22 green root cause: the variable arc (arcXmlTmpPC/variable/*_v.arc) has its own Light0-3 / Filter0-3 /
     Efc0-3 copies, the ones the game uses; lp1map only wrote the main arc, so online00's green tone curves
     (R 0,.11,.24,.73 / B 0,.09,.41,.76) + green bloom stayed. lp1map now writes both; Area921 / Battlegrounds patched
     (all 8 copies of each). Desecration's water planes (o00water/o00water2) were leftovers -> stubbed. LP1 s921
     has no water data at all (only fog in s921env).
13. **Per-map water / lava / data posts (user 2026-10-22).** Blends in lp2-assets/lp1/blend_maps now use the map names.
    Water wanted: Lost Coast, Island (902), Ruins (landing craft at the base). Crimson River: no water, lava floes
    (later: kill on-foot players inside, heavy fast VS damage = a damage volume, 12). Lost Technology (s905) had its
    own data posts: s905 has om7105 / om7106 (+ efm_OM 5002 / 5003 effects) where every other LP1 stage has the
    standard om7100 / om7103. Plan: find how LP2 picks the data post model (ObjSet entry vs a fixed path), port
    om7105 via lp1model, and add a map setting "post model" (custom data posts per map, also for the GUI editor).
   - 2026-10-22 (2) still green after the _v fix: ModCache was fresh and every scheduler / texture / vertex colour /
     CM cube was neutral. Remaining suspect = online00's atmosphere (mpAreaLScattering: Mie 100, density 0.7,
     Rayleigh 10.4,10.5,13 = blue least scattered) over a far bigger map: the sky and distant cliffs are flat green
     like fog. lp2light now sets online01's clear-sky scattering (SCATTER; --keep-atmosphere); packages patched.
     Untested. Shot 3 still showed a bright water strip: on00_suimen (rSwingModel) not stubbed yet, or LP1 geometry.
