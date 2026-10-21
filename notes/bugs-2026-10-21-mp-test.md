# Two-player test 2026-10-21: bugs (user's list) + first triage

## Next session (user's picks, in this order)
1. **Save:** use Gato's save as the reference.
   - It's 90-91 % content complete, so a better test file for everything we'd need.
   - Written by an older, backdated LP2 build that he kept to keep his save. So it's an older save
     format: decode it and convert or import it.
   - Discord's transfer trimmed the name to `...Save-`.
2. **[DL - X/X] not showing for other users.** When the user joined as a client, it showed for them.
   When the user hosted, the others didn't see it. Possibly a DLL mismatch: check both builds.
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
7. **DL not showing on clients.** Content transfer progress (member data `content` = `dl <pct>`) isn't
   shown on the joiner's side.
   - The host sees it, or nobody does?
   - Check the lobby UI hook for remote members' content state.
