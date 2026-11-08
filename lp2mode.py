#!/usr/bin/env python3
r"""Compile a game mode for the xlive mod: <game>/Modes/<name>.lp2mode (the editor's Game Mode window) gets "compiled",
the runtime graph (lp2mapc.script_manifest's form) that xlive's scripts.cpp loads, plus "var_init": the settings'
defaults (by variable). A game runs the mode named in mode.txt in its folder (its name, then "setting = value" lines).

  lp2mode.py FILE.lp2mode [...] [--package GAMEMODES_DIR]

--package also writes GAMEMODES_DIR/<file name>.zip, the form the game loads (GameModes\<name>.zip, before the older
Modes\<name>.lp2mode): mode.json (the manifest: format, name, description, base, settings, requires, content) and
mode.lp2mode (the compiled mode). Files in a "<file name>.content" folder next to the source go in as they are, at
their paths inside it (for later: pickups, weapons, vehicles; game files under nativePC/).
"""
import json, os, sys, zipfile

PACKAGE_FORMAT = 1

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


def manifest(doc, content):
    return {
        "format": PACKAGE_FORMAT,
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "author": doc.get("author", ""),
        "base": doc.get("base", "team"),
        "graph": "mode.lp2mode",
        "settings": [{k: st.get(k) for k in ("var", "label", "kind", "default", "choices", "min", "max") if k in st}
                     for st in doc.get("settings", [])],
        "requires": doc.get("requires", {}),
        # for later: what the mode brings (each listed by its path in the zip)
        "content": {"pickups": [], "weapons": [], "vehicles": [], "files": content},
    }


def package(path, doc, out_dir, log=print):
    stem = os.path.splitext(os.path.basename(path))[0]
    extra = os.path.join(os.path.dirname(os.path.abspath(path)), stem + ".content")
    files = []
    if os.path.isdir(extra):
        for root, _, names in os.walk(extra):
            for n in sorted(names):
                full = os.path.join(root, n)
                rel = os.path.relpath(full, extra).replace(os.sep, "/")
                if rel.lower() in ("mode.json", "mode.lp2mode") or ".." in rel.split("/"):
                    continue
                files.append((rel, full))
    os.makedirs(out_dir, exist_ok=True)
    zpath = os.path.join(out_dir, stem + ".zip")
    tmp = zpath + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mode.json", json.dumps(manifest(doc, [r for r, _ in files]), indent="\t"))
        z.writestr("mode.lp2mode", json.dumps(doc, indent="\t"))
        for rel, full in files:
            z.write(full, rel)
    os.replace(tmp, zpath)
    log(f"{zpath}: packaged ({len(files)} extra file(s))")
    return zpath


def main():
    args = sys.argv[1:]
    out_dir = None
    if "--package" in args:
        i = args.index("--package")
        out_dir = args[i + 1]
        del args[i:i + 2]
    for path in args:
        doc = json.load(open(path))
        doc["compiled"] = compile_mode(doc)
        json.dump(doc, open(path, "w"), indent="\t")
        print(f"{path}: compiled, {len(doc['compiled']['nodes'])} node(s), {len(doc['compiled']['var_names'])} variable(s)")
        if out_dir:
            package(path, doc, out_dir)


if __name__ == "__main__":
    main()
