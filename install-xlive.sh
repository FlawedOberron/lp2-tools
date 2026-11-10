#!/bin/bash
# Installs the built xlive.dll into both LP2 copies (Steam + retail), only while the game is closed; verifies with cmp.
set -e
if [ "$(pgrep -fc 'LP2DX(9|11)\.ex[e]')" != 0 ]; then echo "game running, not installed"; exit 1; fi
S=~/Projects/xlive-steamworks-src/bin/xlive.dll
for d in "/run/media/flawedoberron/54ee05eb-d4ba-43e9-b577-0cf9074323a4/SteamLibrary/steamapps/common/Lost Planet 2" \
         "$HOME/Games/lp2-retail/prefix/drive_c/Program Files (x86)/Capcom/Lost Planet 2"; do
  cp "$S" "$d/xlive.dll" && cmp "$S" "$d/xlive.dll" && echo "ok: $d"
done
