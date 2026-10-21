# Handoff 2026-10-20 → next week. START HERE ("Let's continue the LP2 stuff")

User is usage-limit conscious: keep outputs tight. Rules: ship only our DLL / tools, never game files;
install only when `pgrep -f 'LP2DX(9|1''1)\.exe'` is empty (verify with cmp/diff); commit + push only after
the user tests and approves; pkexec never sudo. Build: `ninja -C ~/Projects/lp2-build/mingw` → 
`~/Projects/xlive-steamworks-src/bin/xlive.dll`. Game dir:
`/run/media/flawedoberron/54ee05eb-d4ba-43e9-b577-0cf9074323a4/SteamLibrary/steamapps/common/Lost Planet 2`.

## State at hand-off (all UNCOMMITTED, awaiting user test/approval)
- xlive (src/mods/packages.*, parts.*, overlay.cpp, docs/LP2-MODS.md): map thumbnails (ID221_SC13/14),
  part `"effects": "none"` (empty rEffectProvider, kGenVersion 15). Installed; backups in game dir:
  xlive.dll.pre-thumb, xlive.dll.pre-noeffects.
- lp2-tools: lp2light.py, lp2thumb.py, lp2layout.py drop_gimmicks + 0x110 index, blender_lp2_map_markers.py
  world(), lp1port.py (cut-out alpha material, --trim-legs, FILE-source images), lp2_blender_export.py
  (effects default none). Details: notes/handoff-2026-10-19-map-port.md (bottom sections).
- Installed sets: LPC_lp1basil (split legs/back, B/C), LPC_lp1basilcb "Basil (Agent)" (hmcb, B/C/D from
  NEVEC FF bd2904), LPC_lp1luka; old LPC_lp1basilnp deleted. Battlegrounds10 map installed. All untested.
- Parked request: MP create-match menu options → notes/requests-mp-menu.md (RE progress there).

## The next 3 steps (user's order)
1. **Unlimited map imports** (planned below — start here)
2. **Network transport for maps & parts** (send missing content in the lobby)
3. **Discord integration**

---------------------------------------------------------------------------------------------------
## 1. Unlimited map imports — plan

### Today
`packages.cpp LoadMaps()`: each `Maps\*.zip` takes one of `kFreeSlots[] = {13, 14}` in file order, is
unpacked (renumbered to that slot) into `ModCache\maps\<pkg>\` and added to the overlay index statically
(`IndexTree`). Third+ zip: "no free map slot left". Names → generated FCORE message files
(`GenerateNames`, MsgOnline map name id 126+?), thumbnails → generated aBattlePlayerCreate.arc
(`GenerateThumbnails`, ID221_SC<slot>_ID). `PackagesGenerated` serves both.

### Design: "carrier" slot, like the parts carrier
Keep slot 13 (and 14) as **carriers**; any number of packages bind to a carrier at match time.
1. **Registry**: LoadMaps unpacks every zip (renumbered to the carrier slot) into its own cache dir but
   does NOT put them in the static index. Keep `std::vector<MapPackage>` + `int g_bound[2]` (package per
   carrier, -1 = none).
2. **Dynamic overlay binding**: overlay lookups for the carrier's files (keys under the slot's paths,
   e.g. `nativepc\...online_13...`; collect the exact key set per package at unpack) resolve through
   the bound package's dir. Need an overlay API `PackagesResolve(rel) -> path` consulted per open
   instead of the prebuilt map (overlay.cpp index is a flat unordered_map; add a second lookup for
   carrier keys, guarded by a mutex since binding changes at runtime).
3. **Picker UX (create match)**: map row L/R. Rules byte [0x1b] = map, pushed to Flash via setter
   `FUN_00f4a330(0x37, value)` (DataNo 0x37 RULE_MAP; push-all `FUN_00e8c270`, controller
   `FUN_00ef6810`, see requests-mp-menu.md). Hook the map change: when the value lands on carrier 13,
   further presses in the same direction step through packages (wrap back to stock maps at the end);
   store the chosen package index; rule value stays 13.
   - **Name**: the map-name string for slot 13 lives in the loaded MsgOnline/FCORE message resource.
     Generate it padded (e.g. 43 bytes of spaces) and rewrite the resident string in memory on every
     change (find via the resource's string table pointer once loaded). Fallback: name "Custom map"
     and show the package name in a log/toast.
   - **Thumbnail**: Flash shows texture ID221_SC13 (frame map+2 of `mc_monitor`). Options, in order:
     (a) overwrite the resident texture's pixels on change (find the rTexture by name in the resource
     manager → its D3D texture → UpdateSubresource/LockRect; same 512² DXT5 size always);
     (b) generic "Custom map" thumbnail. Do (b) first, (a) as polish.
   - Persist the last choice (Saved match settings: the game saves rules; our extra = package hash in
     `ModCache\maps\last.txt`).
4. **Binding time**: bind when the host confirms create-match (rules final) and when a client joins
   (host's choice from lobby/session data — see step 2; until transport exists: lobby metadata key
   `lp2map13=<package hash>`; joiner binds if it has that hash, else refuse join with a message).
   Re-bind only between matches (never while an area is loaded).
5. **Resource cache risk**: the game caches resources by name. Two packages both renumbered to
   ONLINE_13 share names → after playing X, Y may show X's cached stuff. TEST FIRST: play pkg X on 13,
   back to lobby, rebind 13 to Y (temp debug: bind via a hotkey or settings key), play → check. If it
   leaks: give each package unique internal names (like parts' 6-char carrierTok: rename the
   package's own resource paths to a per-package token of identical length, keep only the slot-level
   entry files at the carrier names), or force a resource purge on rebind.
6. **Map-specific shared files**: things currently generated per slot (FCORE names, aBattlePlayerCreate
   thumbnails, any area tables patched for slot 13/14 — check Unpack/renumber for what's shared) must
   become "current binding" outputs and be regenerated on rebind (or made binding-independent).
7. Docs: LP2-MODS.md "two map packages at a time" → carrier description; roadmap item 5 done.

### First session checklist (cheap order)
1. Read packages.cpp Unpack/renumber + overlay.cpp index (what keys a map package contributes).
2. Implement registry + runtime binding + debug rebind (settings key `maps.bind13=<package>`), test
   the cache-leak question with two packages (Battlegrounds + a copy with a changed light/thumbnail).
3. Then the picker hook (RE the L/R handler for the map row in FUN_00ef6810's page/row handling).

---------------------------------------------------------------------------------------------------
## 2. Network transport (maps & parts) — outline
- Already there: SteamNetworkingMessages datagram layer (src/core/net.cpp), lobby member data with
  per-player part sets synced (src/core/memberdata.cpp, commit 0bc3901), part set content hash
  (`PartSet.hash`, MakeBundle: same bundle bytes on every PC), lobby metadata (xlocator.cpp
  SetLobbyData).
- Add: lobby key per needed item (map hash for carrier, each member's part set hashes already in member
  data). Missing hash → request from the owner (host for maps, the member for parts) on a dedicated
  channel; chunked transfer (~1 KB-ish chunks under the message size limit, windowed, resume), size cap
  (e.g. 64 MB maps, 16 MB parts), verify hash, store in `ModCache\net\<hash>.zip`, load as a normal
  package (maps → registry; parts → registry with "remote" flag, not shown in own menu unless kept).
- Safety: data-only (zip of nativePC files / lpc bundle), path sanitising on unpack (no `..`, no
  absolute), never executable content; optional consent setting ("download lobby content": ask/always/never).
- UI: progress in log + a simple overlay/toast; block "ready" until done or show stock fallback for
  parts (part → its template) if transfer fails.

## 3. Discord integration — outline
- Discord app "Lost Planet 2 (Recolonised)" (user made it): App ID 1562087240098906242 (memory lp2-discord-app; public key there too).
- Rich presence from the DLL: Discord local IPC (named pipe `\\.\pipe\discord-ipc-0`, JSON
  SET_ACTIVITY) — no SDK needed; under Proton the pipe needs a bridge (e.g. wine-discord-ipc-bridge /
  rpc-bridge), document it. Needs a Discord application id (user creates it; assets: map thumbnails).
- Show: mode (campaign/online), map name (custom package names too), match type, players x/y,
  elapsed time; party size from lobby.
- Join: activity join secret = Steam lobby id → on ACTIVITY_JOIN, call the existing lobby-join path
  (xsession/xlocator). Ask-to-join later.
- Settings toggle `discord.enabled`, default off; never send anything but game state.

## 3. Discord — STARTED 2026-10-20 (uncommitted, installed; backup xlive.dll.pre-discord)
- Proton (9/Exp/Hotfix) Wine has NO AF_UNIX (10047) → under Wine the Linux socket is opened via int 0x80 syscalls (rpc-bridge trick; verified handshake outside container).
- src/core/discord.{h,cpp}: own IPC client (no SDK). Tries \\.\pipe\discord-ipc-N, then Wine AF_UNIX
  socket Z:$XDG_RUNTIME_DIR[/app/com.discordapp.Discord|/snap.discord|/app/dev.vencord.Vesktop]/discord-ipc-N
  (user: native Discord, /run/user/1000/discord-ipc-0). Handshake client_id = Cfg().discordAppId
  (default 1562087240098906242; settings "discord": {"enabled", "app_id"}). READY → SUBSCRIBE ACTIVITY_JOIN.
- Activity every 3 s if changed: details = game presence line (UserPresenceText(0)), state "In a lobby"
  + party lp2-<lobby> size [members, limit] + join secret = lobby id (→ events::OnLobbyJoinRequested),
  start timestamp = DLL start, large_image "logo" (upload an asset named logo in the portal).
- Started in XLiveInitialize (after SessionsInit), stopped (activity cleared) in XLiveUninitialize.
- TO VERIFY: log lines "discord: connected to ..." / "ready (user ...)". If never connected: Wine AF_UNIX
  or the Steam runtime container may hide the socket → check log, fall back to a bridge.
- Discord WORKS in game (user confirmed 2026-10-20) after: int 0x80 Linux socket + Linux pid (getpid syscall;
  Wine pid 32 made Discord ignore it). Activity: outside lobby = presence line with "Preparing to play" →
  "In the menu"; in lobby: details "<Player Match>: <mode> (<sub-rule>)" from lobby props 0x10000001 (mode,
  MsgOnline 72..) / 0x10000002 (sub-rule 79../83../88..) — GUESSED from one sample, raw values logged
  ("discord: lobby properties ...") to confirm; state = map (0x10000004; 0-15 stock names, 13/14 = package
  names) or "Lobby: <map>"; SessionPresenceInGame() added to xsession. Join button: unverified, untested.
- Tester zip: ~/Projects/lp2-assets/test-build/lp2-recolonised-test.zip (xlive.dll, steam_api.dll,
  xlive_steamworks.json, README.txt). Rebuild it after DLL changes.
- Discord Join secret only when SessionPresenceJoinable() (lobby type not invisible, and not in-game with join-in-progress disabled). Tester zip rebuilt.

## 2. Network transport — BUILT 2026-10-20 (uncommitted, installed; backup xlive.dll.pre-transfer)
- core/transfer.{h,cpp}: SteamNetworkingMessages channel 0x10001, reliable; request/header/data(64 KB)/
  ack/cancel; window 6 chunks; own pump thread; providers by kind ("part", "map"); TransferFetch blocks,
  streams to <path>.part then renames; stall 20 s; max 4 concurrent serves. net.cpp lifts SendRateMax to
  4 MB/s when network.send_rate_kbytes unset.
- Parts: FetchBundle real players → TransferFetch("part", hash, 64 MB) via ModCache\parts\remote\<hash>.lpcb;
  ServeBundle serves own sets (MakeBundle from SetFolder, re-hash check). Failed fetch retried after 30 s.
- Maps (packages.cpp rewritten): ALL Maps\*.zip load (no 2 limit), hash = FNV-1a 64 of zip; bindings per slot
  13/14 (Prepare → ModCache\maps\<pkg>\s<slot>\, kCacheVersion 3); overlay asks PackagesMapFile first
  (PackagesIndex removed); names/thumbnails regenerate per binding generation. Member data "maps" =
  "13=<hash>;14=<hash>". SyncThread 1 s Reconcile: not in game; in someone else's lobby → bind host's by
  hash or download from host (ModCache\maps\remote\<hash>.zip, 512 MB cap, re-hash) → bind; own lobby / no
  lobby → defaults (first two local zips). Zip entry names sanitised (SafeEntryName).
- maps.cpp: slots 13/14 ALWAYS set up (joiners with no packages); MapAvailable 13/14 = PackagesSlotBound;
  MapsRebind(slot, base, size) re-points preload entry + remap size.
- NOTE for step 1 (unlimited/picker): Reconcile rebinds defaults when hosting — the picker work must make
  the host's chosen package the "own" binding instead.
- TODO / untested: two-player test (tester zip rebuilt); name shown in joiner's lobby menu may be stale
  (FCORE loaded at boot); no UI for download progress (log only); a joiner whose download isn't done when
  the match starts would load their own/empty slot (block ready-up later).

## Start gate + download progress (2026-10-20, built + installed, UNTESTED)
- `core/content.{h,cpp}`: each player publishes member data `content` = `ready` / `dl <pct>`; mods register pending checks (packages: host map unbound or downloading, failed hashes skip 30 s; parts: g_remoteState 0). `TransferProgress()` added.
- `XSessionStart` (all players) holds until every lobby member is ready or `sessions.start_wait_seconds` (180) passes; state stays LOBBY meanwhile, so Reconcile can still bind arrived maps. Members without `content` (vanilla) count as ready.
- Discord state shows "Downloading content (N%)" / "Waiting for N players to download (N%)".
- To verify: the log shows `XSessionStart: starting (overlapped|synchronous)`. Does the game wait on it before loading the stage? If not, gate elsewhere.
- Transfer direction: maps go host → players only; parts go any → any.
- Backup: `xlive.dll.pre-gate`.

## Loopback transfer test (2026-10-20, installed, UNTESTED; backup xlive.dll.pre-loopback)
- `TransferAddLoopback(peer)`: sends to that peer are queued in-process and handled by the pump as if they came from it, so the whole protocol runs without Steam.
- Parts: the fake member (`ModCache\parts\fake_member.txt`, now ON) is a loopback peer. `ServeBundle` also serves `fake_library` sets, and their `remote\<hash>` cache is cleared on each start.
- Maps: `ModCache\maps\loopback.txt` (ON) re-fetches the bound maps from fake host 0x01100001fffffff1 into `ModCache\maps\loopback\`, then binds the copy (package `loopback-<hash>`).
- Turn off: delete `loopback.txt`; rename `fake_member.txt` back to `.off`.

## Settle + per-part bundles (2026-10-20, installed, UNTESTED; backup xlive.dll.pre-partbundles)
- `ContentSettle()`: when a member joins (or we enter a lobby), the lobby counts as not ready for 2.5 s, so a start can't slip through before the newcomer's sets are seen.
- Per-part bundles:
  - `PartSet::partHash[s]` is the hash of `MakeBundle(dir, set, out, only=s)`: that part's files plus `lpc.json` cut to that part (`PartManifest`, using the new `Json::Write`/`Quote`).
  - Member data publishes part hashes (`pkg.setHash` = the part hash).
  - `ServeBundle` serves part hashes, and whole-set hashes for older builds.
  - The remote check accepts a set hash or a part hash.
  - A warning is logged when a part is over 64 MB.
- Results:
  - Loopback test (16:09): map and parts transfer OK; downloaded Battlegrounds played.
  - spx5 not worn because the user's body was stock; it needs a custom body to replace.
  - `XSessionStart` is overlapped and comes about 2 s before the stage load, so the gate is at the right point.
- NEXT (user's order): custom parts in lobbies (the lobby preview shows only our own choice).

## Lobby previews wear members' sets (2026-10-20, DX11 only, installed, UNTESTED; backup xlive.dll.pre-lobbyparts)
- Lobby screens (DX11):
  - `e97b30`: previews at screen+0x6c4+i*4, member entry in ebx at the call.
  - `ea3e80`: previews at screen+0x7d8, member entry in edi.
  - Both dress each member's preview once via preview apply `c3db30` thiscall(P, cat, code, 0).
- Member table `*0x1852850 + 0x148 + i*0x7c`: 16 entries; present flag at +0x64; codes at +0xc+cat*4; name at +0x2c. The XUID offset is found at runtime from our own entry (log line `lobby members keep the XUID at +0x..`).
- Preview fields:
  - P+0x212c: loader character (lobby uses 9-24).
  - P+0x1ff0: parts object.
  - P+0x2084: codes.
  - P+0x20d4: state.
- Hooks:
  - `c3db30` stub (pushal; captures ebx/edi and the return address) records preview → member.
  - `PartRequest` resolves by character; `CarrierFor` resolves by parts object.
  - The `c3dc00` stub reloads via `c3b700` when `g_lobbyGen` bumps (a remote set is built, or member data changes).
  - The map is cleared at the stage request and whenever we're not in a lobby.
- 32-player lobbies would need:
  - the member table, the preview arrays and the loops widened from 16;
  - more loader character slots: `7d41f0` caps at 0x20, and the lobby uses 16 of them plus the menus' few.
- DX9: not hooked (addresses not found yet).

## Committed 94cc164 + release test-2026-10-20c (2026-10-20)
- Loopback results (user saw them in game):
  - Lobby preview hidden → shown with spx5 after the throttled 24 s download.
  - Lobby names set 599 times in 5 s, i.e. every frame, so the tags update live.
  - Names show `[DL x/y z%]`, then `[READY]` (READY itself not yet seen in game).
- Loopback is OFF on the user's install: `fake_member.txt.off`, `loopback.txt.off` (both have `rate` lines; rename to turn back on).
- STILL UNPROVEN: lobby slot → real Steam id (XUID offset in the member table). The fake member skips it. Watch for `lobby members keep the XUID at +0x..` in the two-player test.
- Text setter hook `f4a350` (lobby screens only; text == entry+0x2c).

## 2026-10-20 evening — committed 00b5ffc, 7192b28, 7ef246f, 0bc78e9; release test-2026-10-20e
- Map picker (maps.cpp RuleStep / Message hooks, packages.cpp PackagesPick, bind on the sync thread).
- Match rules (src/mods/rules.cpp, DX11+DX9): unlimited ammo (add-ammo c7aa20 restores total; reserve
  getter c7a820 -> -1 = HUD infinity via counter style 6 hook eca930), unlimited grenades (no HUD inf:
  grenade counter has no style for it), default secondary (spawn 8fb130: player info +0x10+7*4 slot id
  0x04KK0000). Rows on Settings 2 (= Flash sub1; Settings 1 = main page, Settings 3 = sub2): rules bytes
  0x2e-0x30, row table 0x17e9840 page 1, AVM1 DoAction inserted into id221 (also in ID_TITLE*.arc, which
  load first!), items 500-502, DataNo 75-77, texts via RulesMessage. Free: rules bytes 0x31-0x37,
  DataNo 78-127; Settings 3 has room for 3 rows (insert before PCCROSS, which is hidden on PC).
- Next: Weapons on Map (pickup kind rewrite) on Settings 3; secondary variant from Set Weapon; Random.
- Lobby slots matched by gamertag; in-match player info has no account/name (match slot mapping open).
