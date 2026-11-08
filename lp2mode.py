#!/usr/bin/env python3
"""Compile a game mode for the xlive mod: <game>/Modes/<name>.lp2mode (the editor's Game Mode window) gets "compiled",
the runtime graph (lp2mapc.script_manifest's form) that xlive's scripts.cpp loads, plus "var_init": the settings'
defaults (by variable). A game runs the mode named in mode.txt in its folder (its name, then "setting = value" lines).

  lp2mode.py FILE.lp2mode [...]
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp2mapc  # noqa: E402


def setting_value(st):
    kind = st.get("kind", "number")
    d = st.get("default", 0)
    if kind == "onoff":
        return 1.0 if d in (True, 1, "1", "on", "true") else 0.0
    if kind == "choice":   # the choice's number (from 0)
        ch = st.get("choices") or []
        return float(ch.index(d)) if d in ch else float(d) if str(d).lstrip("-").isdigit() else 0.0
    try:
        return float(d)
    except (TypeError, ValueError):
        return 0.0


def compile_mode(doc, log=print):
    graph = doc.get("script") or {"nodes": [], "links": []}
    known = [n for n in graph.get("nodes", []) if n.get("type") in lp2mapc.SCRIPT_TYPES]
    skipped = sorted({n.get("type") for n in graph.get("nodes", [])} - {n.get("type") for n in known})
    if skipped:
        log(f"  mode: node types the game doesn't run yet, left out: {', '.join(skipped)}")
    m = lp2mapc.script_manifest({"scripts": graph, "volumes": []}, log)
    out = m.get("script") or {"nodes": [], "volumes": 0, "start_off": [], "vars": 0, "var_names": [], "var_kinds": []}
    names = out.get("var_names", [])
    init = {}
    for st in doc.get("settings", []):
        v = lp2mapc.script_var_name(st.get("var", ""))
        if v in names:
            init[str(names.index(v))] = setting_value(st)
    out["var_init"] = init
    return out


def main():
    for path in sys.argv[1:]:
        doc = json.load(open(path))
        doc["compiled"] = compile_mode(doc)
        json.dump(doc, open(path, "w"), indent="\t")
        print(f"{path}: compiled, {len(doc['compiled']['nodes'])} node(s), {len(doc['compiled']['var_names'])} variable(s)")


if __name__ == "__main__":
    main()
