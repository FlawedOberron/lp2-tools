#!/usr/bin/env python3
"""Battle-bot brains for the DLL's per-mode brain swap (xlive-steamworks src/mods/bots.cpp), from the stock
rThinkPlanAI tool\\AI\\Think\\HumanBotBt (autoArc\\uHm6d.arc).

  lp2brain.py --game LP2_DIR OUT_MOD_DIR        OUT_MOD_DIR/nativePC/arcLp2Xml/autoArc/uHm6d.arc (Mods overlay)
  lp2brain.py --dump MODE --game LP2_DIR        one brain as text (lp2think.py format)

The overlay is the stock archive plus HumanBotBt_<mode> for mode in MODES (stock HumanBotBt kept). Brains are
the stock one edited by the recipes below (xfstree.py: byte-identical round trip of the stock files).

Plan items (lp2think.py): roots (mAttr 512) by state, run-to items (mAttr 0) whose children are leaf
actions (mAttr 1). Filters must all pass, evaluation weights add up, the best item runs its moves.
FilterWeapon masks (cAIPlanFilterWeapon::vf5, DX9 980410), by the held weapon's kind (+0x1e) and variant
(+0x1c): loadout slots 0x30..0x34 variants 0..6 -> Standard lo bits 18-24, Short range lo 25-31, Long range
hi 0-6, Heavy hi 7-13, Support hi 14-20 (shields: Support 4, 5). mWpMode 0 = held weapon; 3 = the other
weapon (DLL extension).
"""
import argparse, copy, os, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import arcx, lp2mapc, lp2think, xfstree  # noqa: E402

STOCK = "tool\\AI\\Think\\HumanBotBt"
MODES = ("elim", "team", "post", "fox", "egg")

# FilterWeapon 64-bit masks (mWpAttr), by loadout slot
STANDARD = 0x7F << 18
SHORT = 0x7F << 25
LONG = 0x7F << 32
HEAVY = 0x7F << 39
SUPPORT = 0x7F << 46
# fixed (pickup) weapon kinds 0x01..: bit (kind - 1) for 1-7; 0x05 = short range, 0x02 long, 0x04 heavy
SHORT |= 1 << 4
LONG |= 1 << 1
HEAVY |= 1 << 3
ALL = (1 << 64) - 1

# EvaluateAIParam modes (cAIParam bytes, see bots.cpp)
P_QUICK, P_CALM, P_ATTACK, P_HOLD, P_IMPATIENT, P_FOLLOW, P_GRENADE, P_APPEAL = 1, 2, 3, 4, 7, 9, 10, 11


def dti_hash(name):
    return (~zlib.crc32(name.encode())) & 0x7FFFFFFF


class Brain:
    def __init__(self, data):
        self.t = xfstree.read(data)
        self.cls = {c["hash"]: i for i, c in enumerate(self.t["classes"])}
        self.items = self.t["root"]["values"][0][0]["values"][1]   # itemAIInfoArray -> mpArray objects

    # objects
    def fields(self, o):
        return [f["name"] for f in self.t["classes"][o["cls"]]["fields"]]

    def get(self, o, name):
        v = o["values"][self.fields(o).index(name)]
        return v[0] if len(v) == 1 else v

    def set(self, o, name, value):
        o["values"][self.fields(o).index(name)] = [value]
        return o

    def is_a(self, o, cls):
        return self.t["classes"][o["cls"]]["hash"] == dti_hash(cls)

    def new(self, cls, **values):
        """a copy of the first object of that class in the brain, with values set (field names without 'm')"""
        proto = self.find(lambda o: self.is_a(o, cls))
        if proto is None:
            raise KeyError(cls + " not in the brain's class table")
        o = copy.deepcopy(proto)
        for k, v in values.items():
            self.set(o, "m" + k, v)
        return o

    def find(self, pred, o=None):
        o = o or self.t["root"]
        if pred(o):
            return o
        for vs in o["values"]:
            for v in vs:
                if isinstance(v, dict):
                    r = self.find(pred, v)
                    if r is not None:
                        return r
        return None

    # plan items
    def item(self, name, nth=0):
        hits = [i for i in self.items if self.get(i, "mName") == name]
        return hits[nth]

    def lst(self, item, which):
        """the object list of an item: Filter, Evaluation, Move, Next (mItem*IndexArray holder's mpArray)"""
        key = {"Filter": "mFilterFuncList", "Evaluation": "mEvaluationFuncList", "Move": "mMoveFuncList",
               "Next": "mItemNextIndexArray", "Pre": "mItemPreIndexArray"}[which]
        return self.get(item, key)["values"][1]

    def funcs(self, item, which, cls):
        return [o for o in self.lst(item, which) if self.is_a(o, cls)]

    def clone(self, item, name):
        it = copy.deepcopy(item)
        self.set(it, "mName", name)
        self.set(it, "mIndex", len(self.items))
        self.lst(it, "Next").clear()
        self.lst(it, "Pre").clear()
        self.items.append(it)
        return it

    def link(self, parent, child):
        nxt = self.lst(parent, "Next")
        idx = self.get(child, "mIndex")
        if not any(self.get(o, "mValue") == idx for o in nxt):
            proto = self.find(lambda o: self.is_a(o, "rThinkPlanAI::cU32"))
            nxt.append(self.set(copy.deepcopy(proto), "mValue", idx))
            self.lst(child, "Pre").append(self.set(copy.deepcopy(proto), "mValue", self.get(parent, "mIndex")))

    # function objects
    def weapon(self, mask, inverse=0, mode=0):
        return self.new("cAIPlanFilterWeapon", WpMode=mode, WpAttr=mask, WpAttr2=mask, Inverse=inverse, AndCheck=1)

    def dist(self, radius, inner=1, tgt=0):
        return self.new("cAIPlanFilterDistans", TgtType=tgt, Radius=float(radius), IsInner=inner, Inverse=0, AndCheck=1)

    def e_default(self, w):
        return self.new("cAIPlanEvaluateDefault", Weight=float(w))

    def e_dist(self, radius, w, inner=1, tgt=0):
        return self.new("cAIPlanEvaluateDistans", TgtType=tgt, Radius=float(radius), IsInner=inner, IsOnlyHeightCheck=0,
                        Weight=float(w))

    def e_param(self, mode, w):
        return self.new("cAIPlanEvaluateAIParam", CheckParamMode=mode, Weight=float(w))

    def m_action(self, pad):
        return self.new("cAIPlanMoveHmAction", PadAction=pad)

    def m_time(self, frames):
        return self.new("cAIPlanMoveTime", Return=1, Time=frames, IsParamCheck=0)

    def bytes(self):
        return xfstree.write(self.t)


# ---- recipes ------------------------------------------------------------------------------------------------

def improved(b):
    """weapon-aware shooting and weapon changes (every mode)"""
    fight, run = b.item("Fight"), b.item("RunToTarget", 1)          # #28: RunToTarget -> ShotTaregt
    shot = b.item("ShotTaregt")
    # the stock range band (8.5-30 m, best past 15 m) stays for standard / other weapons
    b.lst(shot, "Filter").append(b.weapon(SHORT | LONG | HEAVY, inverse=1))

    close = b.clone(shot, "ShotClose")                               # shotguns: up close
    f = b.lst(close, "Filter")
    f[:] = [b.weapon(SHORT), b.dist(1500)] + [o for o in f if b.is_a(o, "cAIPlanFilterCharStatus") or
                                             b.is_a(o, "cAIPlanFilterCharIsXXX")]
    b.lst(close, "Evaluation")[:] = [b.e_default(750), b.e_dist(600, 500), b.e_dist(1000, -400, inner=0),
                                     b.e_param(P_ATTACK, 300)]
    for m in b.funcs(close, "Move", "cAIPlanMoveDistance"):
        b.set(m, "mRadius", 150.0)
    run_close = b.clone(run, "RunToTargetClose")
    for m in b.funcs(run_close, "Move", "cAIPlanMoveTrace"):
        b.set(m, "mArriveRadius", 250.0)
    b.link(run_close, close)
    b.link(fight, run_close)

    far = b.clone(shot, "ShotLong")                                  # rifles / snipers: keep distance
    f = b.lst(far, "Filter")
    f[:] = [b.weapon(LONG), b.dist(6000), b.dist(1200, inner=0)] + [o for o in f if b.is_a(o, "cAIPlanFilterCharStatus")
                                                                   or b.is_a(o, "cAIPlanFilterCharIsXXX")]
    b.lst(far, "Evaluation")[:] = [b.e_default(750), b.e_dist(2500, 400, inner=0), b.e_dist(1500, -400),
                                   b.e_param(P_HOLD, 200)]
    b.link(run, far)

    heavy = b.clone(shot, "ShotHeavy")                               # rockets: never point blank
    f = b.lst(heavy, "Filter")
    f[:] = [b.weapon(HEAVY), b.dist(4000), b.dist(700, inner=0)] + [o for o in f if b.is_a(o, "cAIPlanFilterCharStatus")
                                                                   or b.is_a(o, "cAIPlanFilterCharIsXXX")]
    b.lst(heavy, "Evaluation")[:] = [b.e_default(750), b.e_dist(1000, -600), b.e_param(P_ATTACK, 100)]
    b.link(run, heavy)

    # weapon changes by range, only when the other weapon suits it (FilterWeapon mode 3, the DLL)
    change = b.item("WpChange")

    def swap(name, filters, weight):
        it = b.clone(change, name)
        b.lst(it, "Filter")[:] = filters
        b.lst(it, "Evaluation")[:] = [b.e_default(weight)]
        b.lst(it, "Move")[:] = [b.m_action(14), b.m_time(40)]
        b.link(fight, it)

    swap("WpChange-Close", [b.dist(800), b.weapon(SHORT, inverse=1), b.weapon(SHORT, mode=3)], 1300)
    swap("WpChange-Far", [b.dist(1800, inner=0), b.weapon(SHORT), b.weapon(SHORT, inverse=1, mode=3)], 1100)
    swap("WpChange-HeavyClose", [b.dist(600), b.weapon(HEAVY), b.weapon(HEAVY, inverse=1, mode=3)], 1300)
    swap("WpChange-Long", [b.dist(2500, inner=0), b.weapon(LONG, inverse=1), b.weapon(LONG, mode=3)], 900)


def post_grab(b):
    """Post Grab: posts first, anywhere, and keep capturing under light fire"""
    run, ex = b.item("RunToDataPost"), b.item("ExecDataPost")
    for f in b.funcs(ex, "Filter", "cAIPlanFilterDistans"):
        if b.get(f, "mTgtType") == 16:
            b.set(f, "mRadius", 30000.0)                             # any post on the map (was 15 m)
        else:
            b.set(f, "mRadius", 250.0)                               # an enemy this close stops it (was 5 m)
    for e in b.lst(ex, "Evaluation"):
        if b.is_a(e, "cAIPlanEvaluateDefault"):
            b.set(e, "mWeight", 2200.0)                              # was 300
        elif b.is_a(e, "cAIPlanEvaluateDamageRemain"):
            b.set(e, "mWeight", -15.0)
    b.lst(ex, "Evaluation").append(b.e_param(P_IMPATIENT, 300))
    for item, limit in ((ex, 60.0), (run, 150.0)):
        for m in b.lst(item, "Move"):
            if b.is_a(m, "cAIPlanMoveDamage"):
                b.set(m, "mDamageLimit", limit)
            elif b.is_a(m, "cAIPlanMoveDistance"):
                b.set(m, "mRadius", 200.0)


def egg(b):
    """Akrid Egg: go for the egg and the goal harder, escort the carrier"""
    for name, w in (("GetEgg", 3000.0), ("RunEggGoal", 1500.0), ("RunToGoal_Egg", 1200.0)):
        for e in b.funcs(b.item(name), "Evaluation", "cAIPlanEvaluateDefault"):
            b.set(e, "mWeight", w)
    for e in b.funcs(b.item("FriendFollow"), "Evaluation", "cAIPlanEvaluateAIParam"):
        b.set(e, "mWeight", 1500.0)


RECIPES = {"elim": [improved], "team": [improved], "post": [improved, post_grab], "fox": [improved],
           "egg": [improved, egg]}


def build(stock, mode):
    b = Brain(stock)
    for r in RECIPES[mode]:
        r(b)
    out = b.bytes()
    xfstree.read(out)   # parses back
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--dump")
    ap.add_argument("out", nargs="?")
    a = ap.parse_args()
    src = os.path.join(a.game, "nativePC", "arcLp2Xml", "autoArc", "uHm6d.arc")
    stock = next(d for n, d in lp2mapc.entries(src)["rThinkPlanAI"] if n == STOCK)
    if a.dump:
        print(lp2think.dump(build(stock, a.dump), lp2think.class_names(lp2think.CLASSES)))
        return
    if not a.out:
        raise SystemExit("OUT_MOD_DIR needed")
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        args = []
        for m in MODES:
            p = os.path.join(tmp, m + ".rThinkPlanAI")
            open(p, "wb").write(build(stock, m))
            args.append("%s_%s.rThinkPlanAI=%s" % (STOCK, m, p))
        dst = os.path.join(a.out, "nativePC", "arcLp2Xml", "autoArc", "uHm6d.arc")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        subprocess.run([sys.executable, os.path.join(HERE, "arcput.py"), "--add", src, dst] + args, check=True)


if __name__ == "__main__":
    main()
