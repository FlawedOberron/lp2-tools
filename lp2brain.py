#!/usr/bin/env python3
"""Battle-bot brains for the DLL's per-mode brain swap (xlive-steamworks src/mods/bots.cpp), from the stock
rThinkPlanAI tool\\AI\\Think\\HumanBotBt (autoArc\\uHm6d.arc).

  lp2brain.py --game LP2_DIR OUT_MOD_DIR        OUT_MOD_DIR/nativePC/arcLp2Xml/autoArc/uHm6d.arc (Mods overlay)
  lp2brain.py --dump MODE --game LP2_DIR        one brain as text (lp2think.py format)
  lp2brain.py --header brains.h --game LP2_DIR  the brains embedded in the DLL (src/mods/brains.h); rerun after editing a recipe

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
P_TARGET_RELOAD = 15                                                                  # DLL only (bots.cpp EvalParam): 100 while the target reloads
P_POST_FREE, P_OWN_LIFE, P_TARGET_LIFE = 12, 13, 14                                  # percent, written by the DLL (bots.cpp LifePercent)


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
        # Ids in write order, as stock files have them: the game's reader keeps its objects in a table by id, and
        # copied items would otherwise share their prototype's id (crashed AI Enemy Battle on load, 2026-11-03).
        n = [0]

        def number(ob):
            ob["id"] = n[0]
            n[0] += 1
            for vs in ob["values"]:
                for v in vs:
                    if isinstance(v, dict) and "cls" in v:
                        number(v)
        number(self.t["root"])
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
    # a shotgun's spread wastes shots from range: it closes in without firing (rifles keep firing as they close)
    b.lst(run_close, "Move")[:] = [m for m in b.lst(run_close, "Move") if not b.is_a(m, "cAIPlanMoveShot")]
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

    # standard weapons fire past the stock 30 m, so a rifle bot answers a rifle
    for f in b.funcs(shot, "Filter", "cAIPlanFilterDistans"):
        if b.get(f, "mIsInner"):
            b.set(f, "mRadius", 6000.0)
        else:
            b.set(f, "mRadius", 150.0)    # was 8.5 m: closer than that a rifle bot had no shot and sprinted at its target
    for m in b.funcs(shot, "Move", "cAIPlanMoveDistance"):
        b.set(m, "mRadius", 150.0)        # was 5 m: the shot stopped as the target came close

    # Self-preservation. EvaluateDamageRemain is the recent damage / 1000 (it decays): tuned for rockets in stock, a rifle
    # burst barely moved the scores. Hurt now: cover first (needs a cover point in reach), else dodge; standing around scores low.
    for name, weight in (("Avoid", 1500.0), ("WaitCoverP", 4000.0), ("WaitAI-P", 4000.0), ("WaitShotP", -2500.0)):
        for e in b.funcs(b.item(name), "Evaluation", "cAIPlanEvaluateDamageRemain"):
            b.set(e, "mWeight", weight)
    wait, avoid = b.item("Wait"), b.item("Avoid")
    # dodging was most of a bot-vs-bot fight (3000 on damage, 1000 on quickness): rolls now come under heavier fire
    for e in b.funcs(avoid, "Evaluation", "cAIPlanEvaluateAIParam"):
        b.set(e, "mWeight", 600.0)
    hurt = copy.deepcopy(b.funcs(avoid, "Evaluation", "cAIPlanEvaluateDamageRemain")[0])
    b.set(hurt, "mWeight", -2500.0)
    b.lst(wait, "Evaluation").append(hurt)

    # Low on life: cover outbids more the lower it gets (nothing at full life). e_param scores weight x percent / 100.
    for name in ("WaitCoverP", "WaitAI-P"):
        b.lst(b.item(name), "Evaluation").extend([b.e_default(1500), b.e_param(P_OWN_LIFE, -1500)])

    # Finish a hurt target: close in while it's under about half life, unless hurt too. A normal shot scores about 1100.
    finish = b.clone(shot, "ShotFinish")
    f = b.lst(finish, "Filter")
    f[:] = [b.dist(2500), b.dist(400, inner=0)] + [o for o in f if b.is_a(o, "cAIPlanFilterCharStatus") or
                                                   b.is_a(o, "cAIPlanFilterCharIsXXX")]
    b.lst(finish, "Evaluation")[:] = [b.e_default(1100), b.e_param(P_TARGET_LIFE, -1000), b.e_param(P_OWN_LIFE, 400),
                                      b.e_param(P_ATTACK, 100)]
    for m in b.funcs(finish, "Move", "cAIPlanMoveDistance"):
        b.set(m, "mRadius", 300.0)
    run_finish = b.clone(run, "RunToTargetFinish")
    for m in b.funcs(run_finish, "Move", "cAIPlanMoveTrace"):
        b.set(m, "mArriveRadius", 400.0)
    b.link(run_finish, finish)
    b.link(fight, run_finish)

    # Reloading: stock runs to cover first, but its 600 at best never beat a shot. EvaluateReload is 1 - magazine / full, so
    # now cover wins from about a third of a magazine, if a cover point is within 15 m and the target isn't on top of the bot
    # (type 10 is the game's scored CoverPoint; no point found fails the filter). Failing that: reload on the spot when
    # nearly empty.
    reload_cover = b.item("Reload")
    here = b.clone(reload_cover, "ReloadHere")
    b.lst(reload_cover, "Filter").extend([b.dist(1500, tgt=10), b.dist(500, inner=0)])
    for item, offset in ((reload_cover, -400), (here, -1000)):
        for e in b.funcs(item, "Evaluation", "cAIPlanEvaluateReload"):
            b.set(e, "mWeight", 2400.0)
        b.lst(item, "Evaluation").append(b.e_default(offset))
    b.link(fight, here)

    # Pickups: worth a longer walk (was 14 m), but not while being shot.
    get = b.item("GetWp")
    for f in b.funcs(get, "Filter", "cAIPlanFilterDistans"):
        b.set(f, "mRadius", 3000.0)
    for e in b.funcs(get, "Evaluation", "cAIPlanEvaluateDefault"):
        b.set(e, "mWeight", 700.0)
    for e in b.funcs(get, "Evaluation", "cAIPlanEvaluateDamageRemain"):
        b.set(e, "mWeight", -2000.0)

    # A held shield is the defence, so dodging is the last resort: Avoid is off with one up, and a weak copy takes over that
    # only outbids the rest under heavy fire. Stock's own shield test (FightShield's filter): inverse = a shield is held.
    held = copy.deepcopy(b.funcs(b.item("FightShield"), "Filter", "cAIPlanFilterWeapon")[0])
    b.set(held, "mInverse", 1)
    unheld = copy.deepcopy(held)
    b.set(unheld, "mInverse", 0)
    dodge = b.clone(avoid, "Avoid-Shield")
    b.lst(dodge, "Filter")[:] = [held]
    b.lst(avoid, "Filter").append(unheld)
    for e, weight in ((b.funcs(dodge, "Evaluation", "cAIPlanEvaluateDamageRemain")[0], 1000.0),
                      (b.funcs(dodge, "Evaluation", "cAIPlanEvaluateDefault")[0], 100.0),
                      (b.funcs(dodge, "Evaluation", "cAIPlanEvaluateAIParam")[0], 200.0)):
        b.set(e, "mWeight", weight)
    b.link(fight, dodge)

    # Dodge when it helps: under fire out of the weapon's best range (to get there), not where the weapon does its work. Avoid
    # becomes one item per weapon class, each marked down inside that class's range (standard <40 m, shotgun <12 m, long and
    # heavy beyond 12 / 7 m). Which way the roll goes is the game's.
    def class_dodge(name, weapon_filter, radius, inner):
        it = avoid if name is None else b.clone(avoid, name)
        if name is not None:
            b.link(fight, it)
        b.lst(it, "Filter").append(weapon_filter)
        b.lst(it, "Evaluation").append(b.e_dist(radius, -800, inner=inner))
    class_dodge("Avoid-Short", b.weapon(SHORT), 1200, 1)
    class_dodge("Avoid-Long", b.weapon(LONG), 1200, 0)
    class_dodge("Avoid-Heavy", b.weapon(HEAVY), 700, 0)
    class_dodge(None, b.weapon(SHORT | LONG | HEAVY, inverse=1), 4000, 1)

    # The target is reloading: press in to the weapon's best range. Rifles fire as they go (stop at 15 m), shotguns just close
    # (stop at 4 m); long and heavy weapons keep shooting from where they are. Scores nothing unless the DLL sees a reload.
    def push(name, weapon_filter, beyond, arrive, shoot):
        it = b.clone(run, name)
        b.lst(it, "Filter")[:] = [weapon_filter, b.dist(beyond, inner=0)]
        b.lst(it, "Evaluation")[:] = [b.e_param(P_TARGET_RELOAD, 1600)]
        for m in b.funcs(it, "Move", "cAIPlanMoveTrace"):
            b.set(m, "mArriveRadius", float(arrive))
        if not shoot:
            b.lst(it, "Move")[:] = [m for m in b.lst(it, "Move") if not b.is_a(m, "cAIPlanMoveShot")]
        b.link(fight, it)
    push("PushReload", b.weapon(SHORT | LONG | HEAVY, inverse=1), 1500, 1500, True)
    push("PushReload-Short", b.weapon(SHORT), 600, 400, False)

    # weapon changes by range, only when the other weapon suits it (FilterWeapon mode 3, the DLL)
    change = b.item("WpChange")

    def swap(name, filters, weight):
        it = b.clone(change, name)
        b.lst(it, "Filter")[:] = filters
        # under fire, out of range: switching beats dodging or trading shots badly
        under_fire = copy.deepcopy(b.funcs(avoid, "Evaluation", "cAIPlanEvaluateDamageRemain")[0])
        b.set(under_fire, "mWeight", 800.0)
        b.lst(it, "Evaluation")[:] = [b.e_default(weight), under_fire]
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


def post_seek(b):
    """Elimination modes: posts give radar, so take them when nobody's close. Fights come first within 20 m or under fire."""
    ex = b.item("ExecDataPost")
    for f in b.funcs(ex, "Filter", "cAIPlanFilterDistans"):
        if b.get(f, "mTgtType") == 16:
            b.set(f, "mRadius", 6000.0)                              # was 15 m
    for e in b.funcs(ex, "Evaluation", "cAIPlanEvaluateDamageRemain"):
        b.set(e, "mWeight", -2000.0)
    # P_POST_FREE (DLL): 100 when there's a post to take. With no post, the game's post target falls back on the bot's own spot.
    b.lst(ex, "Evaluation").extend([b.e_param(P_POST_FREE, 700), b.e_dist(2000, -700)])


def egg(b):
    """Akrid Egg: go for the egg and the goal harder, escort the carrier"""
    for name, w in (("GetEgg", 3000.0), ("RunEggGoal", 1500.0), ("RunToGoal_Egg", 1200.0)):
        for e in b.funcs(b.item(name), "Evaluation", "cAIPlanEvaluateDefault"):
            b.set(e, "mWeight", w)
    for e in b.funcs(b.item("FriendFollow"), "Evaluation", "cAIPlanEvaluateAIParam"):
        b.set(e, "mWeight", 1500.0)


def post_far(b):
    """Elimination modes, nobody to fight: a post anywhere on the map comes before roaming (user's order: noise, posts, roam).
    A copy, so a bot in a fight only breaks off for the near posts post_seek allows."""
    run, ex = b.clone(b.item("RunToDataPost"), "RunToPostFar"), b.clone(b.item("ExecDataPost"), "ExecPostFar")
    for f in b.funcs(ex, "Filter", "cAIPlanFilterDistans"):
        if b.get(f, "mTgtType") == 16:
            b.set(f, "mRadius", 100000.0)
    b.link(run, ex)
    near = b.get(b.item("RunToDataPost"), "mIndex")
    for root in (b.item("NoTarget"), b.item("TargetDie")):
        nxt = b.lst(root, "Next")
        nxt[:] = [o for o in nxt if b.get(o, "mValue") != near]
        b.link(root, run)


def roam(b):
    """Idle bots travel: stock RUN / RunToPatrol go to ShotPoint, 3-10 m away (Pef_Hm40). Target 20 (FreePoint, unused by stock)
    is the DLL's goal instead (bots.cpp Resolve): gunfire, else a far spawn point. A known target far away gets pushed."""
    run = b.item("RUN")
    push = b.clone(run, "PushTarget")
    for it in (run, b.item("RunToPatrol")):
        for m in b.funcs(it, "Move", "cAIPlanMoveTrace"):
            b.set(m, "mTgtType", 20)
    for m in b.funcs(push, "Move", "cAIPlanMoveTrace"):
        b.set(m, "mTgtType", 0)
    b.set(push, "mRootAttr", b.get(b.item("ShotTaregt"), "mRootAttr"))
    b.lst(push, "Filter")[:] = [b.dist(3000, inner=0)]
    b.lst(push, "Evaluation")[:] = [b.e_default(1000), b.e_param(P_ATTACK, 300)]
    b.lst(push, "Move").append(b.new("cAIPlanMoveShot", NoShotAttr=0))
    b.link(b.item("Fight"), push)


def roam_goal(b):
    """RunToGoal's target 5 (a mode goal) is nothing in these modes: it "arrives" at once, the bot idles a second and repeats
    (seen 2026-11-08 after posts). It goes to the DLL's roam goal (20) instead."""
    for m in b.funcs(b.item("RunToGoal"), "Move", "cAIPlanMoveTrace"):
        b.set(m, "mTgtType", 20)


RECIPES = {"elim": [improved, post_seek, post_far, roam, roam_goal], "team": [improved, post_seek, post_far, roam, roam_goal],
           "post": [improved, post_grab, roam], "fox": [improved, roam, roam_goal], "egg": [improved, egg, roam]}


def build(stock, mode):
    b = Brain(stock)
    for r in RECIPES[mode]:
        r(b)
    out = b.bytes()
    xfstree.read(out)   # parses back
    return out


def delta(stock, out, k=12):
    """COPY / ADD ops rebuilding out from stock: varint (length << 1 | copy), then a varint offset or the literal bytes."""
    index = {}
    for i in range(len(stock) - k):
        index.setdefault(stock[i:i + k], []).append(i)
    ops, i, lit = bytearray(), 0, bytearray()

    def varint(v):
        while v >= 0x80:
            ops.append(v & 0x7F | 0x80)
            v >>= 7
        ops.append(v)

    def flush():
        if lit:
            varint(len(lit) << 1)
            ops.extend(lit)
            lit.clear()
    while i < len(out):
        best, at = 0, 0
        for c in index.get(out[i:i + k], []):
            n = k
            while c + n < len(stock) and i + n < len(out) and stock[c + n] == out[i + n]:
                n += 1
            if n > best:
                best, at = n, c
        if best:
            flush()
            varint(best << 1 | 1)
            varint(at)
            i += best
        else:
            lit.append(out[i])
            i += 1
    flush()
    return bytes(ops)


def undelta(stock, ops):
    out, i = bytearray(), 0

    def varint():
        nonlocal i
        v, sh = 0, 0
        while True:
            b = ops[i]
            i += 1
            v |= (b & 0x7F) << sh
            sh += 7
            if b < 0x80:
                return v
    while i < len(ops):
        n = varint()
        if n & 1:
            at = varint()
            out += stock[at:at + (n >> 1)]
        else:
            out += ops[i:i + (n >> 1)]
            i += n >> 1
    return bytes(out)


def write_header(stock, path):
    """The DLL's embedded brains (bots.cpp): edits against the player's own stock file, none of the file itself."""
    with open(path, "w", newline="\n") as f:
        f.write("// Made by lp2-tools/lp2brain.py --header: each brain as COPY / ADD ops against the stock HumanBotBt.\n#pragma once\n#include <cstdint>\n\n")
        f.write("static const uint32_t kBrainStockSize = %d;\nstatic const uint32_t kBrainStockCrc = 0x%08x;\n\n" % (len(stock), zlib.crc32(stock)))
        seen, rows = {}, []
        for m in MODES:
            out = build(stock, m)
            ops = delta(stock, out)
            if undelta(stock, ops) != out:
                raise SystemExit("delta does not rebuild " + m)
            if ops not in seen:
                seen[ops] = "kBrainOps_" + m
                f.write("static const uint8_t %s[] = {\n" % seen[ops])
                for i in range(0, len(ops), 32):
                    f.write(",".join(str(b) for b in ops[i:i + 32]) + ",\n")
                f.write("};\n\n")
            rows.append((m, seen[ops], len(ops), len(out), zlib.crc32(out)))
            print(m, len(out), "->", len(ops), "bytes of ops,", seen[ops])
        f.write("struct EmbeddedBrain {\n\tconst char* mode;\n\tconst uint8_t* ops;\n\tuint32_t opsSize, size, crc;\n};\nstatic const EmbeddedBrain kEmbeddedBrains[] = {\n")
        for m, name, n, size, crc in rows:
            f.write('\t{"%s", %s, %d, %d, 0x%08x},\n' % (m, name, n, size, crc))
        f.write("};\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--dump")
    ap.add_argument("--header", help="write the DLL's embedded brains (src/mods/brains.h)")
    ap.add_argument("out", nargs="?")
    a = ap.parse_args()
    src = os.path.join(a.game, "nativePC", "arcLp2Xml", "autoArc", "uHm6d.arc")
    stock = next(d for n, d in lp2mapc.entries(src)["rThinkPlanAI"] if n == STOCK)
    if a.dump:
        print(lp2think.dump(build(stock, a.dump), lp2think.class_names(lp2think.CLASSES)))
        return
    if a.header:
        write_header(stock, a.header)
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
