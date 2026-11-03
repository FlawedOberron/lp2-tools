#!/bin/bash
# Builds navgen (Recast from ~/Projects/recastnavigation, zlib licence) next to this script: navgen (Linux) and
# navgen.exe (Windows, 32-bit MinGW, static: runs on any Windows without extra DLLs).
set -e
D=$(dirname "$(realpath "$0")"); R=${RECAST:-$HOME/Projects/recastnavigation}/Recast
g++ -O2 -std=c++17 -static-libgcc -I"$R/Include" "$D/navgen.cpp" "$R"/Source/*.cpp -o "$D/navgen"
if command -v i686-w64-mingw32-g++ >/dev/null; then
	i686-w64-mingw32-g++ -O2 -std=c++17 -static -I"$R/Include" "$D/navgen.cpp" "$R"/Source/*.cpp -o "$D/navgen.exe"
fi
