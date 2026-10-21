# lp2-tools

Modding tools for **Lost Planet 2** (PC), made alongside
[Lost Planet 2 (Recolonised)](https://github.com/FlawedOberron/xlive-steamworks-lp2), the Steamworks
`xlive.dll` that loads custom maps and character parts.

- **[Maps](README-maps.md):** port Lost Planet 1 / Colonies multiplayer maps to LP2 (`lp1map.py`, one
  command), and edit spawns, VS, weapons and data posts in Blender (`blender_lp2_map_markers.py`).
- **[Character parts](README-parts.md):** import LP2 parts into Blender, model or re-rig them, and export new
  part sets (`lp2_blender_import.py`, `lp2_blender_export.py`, `lp1port.py` for LP1 characters).
- **File formats:** readers and writers for MT Framework archives, models, textures, collision, Havok
  physics, layouts, lighting and saves. Each script's docstring describes its format.

Requirements: Python 3 with `numpy` and `Pillow`, Blender 4+ for the Blender parts.

**No game files.** This repository contains only code. Everything the tools produce is built from your own
copies of the games, and output stays on your machine (or goes to players who own the game, through the
DLL's lobby transfer).

`notes/` holds working notes from reverse engineering the game (addresses, formats, test logs). They are
unpolished and kept as a reference.

Lost Planet is © Capcom. This project is not affiliated with Capcom.
