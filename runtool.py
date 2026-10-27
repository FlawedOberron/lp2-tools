#!/usr/bin/env python3
"""Runs a tool for the Map Editor: runtool.py SCRIPT [ARGS...] with its stderr on stdout, so the editor reads one
pipe on every platform (no shell)."""
import os, runpy, sys

os.dup2(1, 2)
sys.stderr = sys.stdout
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
runpy.run_path(script, run_name="__main__")
