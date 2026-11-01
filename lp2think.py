#!/usr/bin/env python3
"""Dump an rThinkPlanAI (bot brain: tool\\AI\\Think\\HumanBotBt in uHm6d.arc = battle bots, HumanBotCp in
ID_CORE_MULTI.arc = campaign partners, HumanBotAt in ID_CORE_PC.arc) as readable plan items.

  lp2think.py FILE.rThinkPlanAI [CLASSES.txt]

XFS (xfs.py). Root mSaveInfo.itemAIInfoArray = plan items {mName, mIndex, mAttr, mRootAttr, mItemNextIndexArray
(children), mFilterFuncList (cAIPlanFilter*: all must pass), mEvaluationFuncList (cAIPlanEvaluate*: summed weights,
best item wins), mMoveFuncList (cAIPlanMove*: what it does)}. Class hashes are named from the decompile's
classes.txt (MT DTI hash = ~crc32(name) & 0x7fffffff).
"""
import json, os, re, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xfs  # noqa: E402

CLASSES = "/run/media/flawedoberron/b3b6c314-29ca-4605-8d94-6ebff4c7d1ac/lp2-decomp/dx9/classes.txt"


def class_names(path):
    names = re.findall(r"^\s*(\S+)\s+size", open(path).read(), re.M) if os.path.exists(path) else []
    return {"%08x" % ((~zlib.crc32(n.encode())) & 0x7FFFFFFF): n for n in names}


def dump(data, names):
    r = xfs.parse(data)
    nm = lambda o: names.get(o.get("_class"), o.get("_class")).replace("cAIPlan", "")
    out = []
    for it in r["mSaveInfo.itemAIInfoArray"]["mpArray"]:
        arr = lambda k: it[k]["mpArray"] if isinstance(it[k], dict) else []
        out.append("#%d %s attr=%s root=%s next=%s" % (it["mIndex"], it["mName"], it["mAttr"], it["mRootAttr"],
                                                      [x["mValue"] for x in arr("mItemNextIndexArray")]))
        for k, lab in (("mFilterFuncList", "F"), ("mEvaluationFuncList", "E"), ("mMoveFuncList", "M")):
            for x in arr(k):
                a = {f: v for f, v in x.items() if f != "_class" and not isinstance(v, (dict, list))}
                out.append("    %s %s%s" % (lab, nm(x), json.dumps(a) if a else ""))
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(dump(open(sys.argv[1], "rb").read(), class_names(sys.argv[2] if len(sys.argv) > 2 else CLASSES)))
