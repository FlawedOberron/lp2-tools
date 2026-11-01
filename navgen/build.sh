#!/bin/bash
# Builds navgen (Recast from ~/Projects/recastnavigation, zlib licence) next to this script.
set -e
D=$(dirname "$(realpath "$0")"); R=${RECAST:-$HOME/Projects/recastnavigation}/Recast
g++ -O2 -std=c++17 -I"$R/Include" "$D/navgen.cpp" "$R"/Source/*.cpp -o "$D/navgen"
