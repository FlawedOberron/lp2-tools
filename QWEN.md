# Lost Planet 2 "Recolonised" project

Start here, in this order:
1. ~/.claude/projects/-home-flawedoberron/memory/lp2-gfwl-revival.md (paths, rules, where everything lives)
2. notes/handoff-2026-10-28-next.md (next steps, in order), the newest other notes/handoff-*.md, then notes/bugs-2026-10-21-mp-test.md (open bugs; newest entries at the end)
3. notes/map-editor-plan.md (editor roadmap), notes/vs-ids.md (VS findings)

Repos: ~/Projects/lp2-tools (Python tools, this folder), ~/Projects/lp2-editor (Godot 4 map editor),
~/Projects/xlive-steamworks-src (the replacement xlive.dll, C++, built with ../lp2-build/mingw),
~/Projects/lp2-mapedit (public editor release repo), ~/Projects/lp2-assets (projects, maps, mods, renders).
Game: /run/media/flawedoberron/54ee05eb-d4ba-43e9-b577-0cf9074323a4/SteamLibrary/steamapps/common/Lost Planet 2

Rules (the user's, never break them):
- Install into the game folder only while the game is closed: `pgrep -f 'LP2DX(9|11)\.exe'` must find nothing;
  check every copy with cmp afterwards.
- No backups of xlive.dll / json in the game folder (only the .capcom originals). Ship only our DLL, never game files.
- Every DLL feature must work in both LP2DX9.exe and LP2DX11.exe.
- Don't commit or release until the user has tested in game and said so.
- Write findings into the notes above (dated), so Claude can continue from them.
