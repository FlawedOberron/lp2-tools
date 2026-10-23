# Readable names for Lost Planet 2's humanoid joints (the global joint ids every hm part shares: "j013").
#
# The game's side convention: -X is the character's left (LP2 is left-handed, characters face +Z).
# The Blender scripts name bones and vertex groups with NAMES; they read any of the aliases below, the old
# "jNNN" form, or the name itself in any case / separator style ("R_UpperArm", "upperarm.R", "upper_arm_r").
#
#   python3 lp2bones.py            the table (joint, name, parent)

import re

# joint id -> (name, parent joint id or None)
JOINTS = {
    0: ("root", None),
    1: ("pelvis", 0),
    2: ("l_thigh", 1), 3: ("l_shin", 2), 4: ("l_foot", 3),
    5: ("r_thigh", 1), 6: ("r_shin", 5), 7: ("r_foot", 6),
    8: ("spine", 0),
    9: ("chest", 8),
    10: ("neck", 9),
    11: ("head", 10),
    12: ("l_shoulder", 9), 13: ("l_upperarm", 12), 14: ("l_forearm", 13), 15: ("l_hand", 14), 20: ("l_fingers", 15),
    16: ("r_shoulder", 9), 17: ("r_upperarm", 16), 18: ("r_forearm", 17), 19: ("r_hand", 18), 21: ("r_fingers", 19),
    # stock chains (bone physics): hair / head pieces, back flap, chest front
    32: ("l_head_front_1", 11), 33: ("l_head_front_2", 32), 34: ("l_head_back_1", 11), 35: ("l_head_back_2", 34),
    36: ("r_head_front_1", 11), 37: ("r_head_front_2", 36), 38: ("r_head_back_1", 11), 39: ("r_head_back_2", 38),
    40: ("back_flap_1", 9), 41: ("back_flap_2", 40),
    42: ("l_chest_1", 9), 43: ("l_chest_2", 42), 44: ("r_chest_1", 9), 45: ("r_chest_2", 44),
    # attachment points
    100: ("back_mount", 9),
    101: ("r_hand_mount", 18),
}

# other spellings people (and other rigs) use -> our name; matched after normalising (see key())
_ALIASES = {
    "hips": "pelvis", "hip": "pelvis", "waist": "pelvis",
    "spine1": "spine", "abdomen": "spine", "belly": "spine",
    "spine2": "chest", "upperchest": "chest", "torso": "chest", "ribcage": "chest",
    "clavicle": "shoulder", "collar": "shoulder", "collarbone": "shoulder",
    "arm": "upperarm", "upperarm": "upperarm", "bicep": "upperarm",
    "lowerarm": "forearm", "elbow": "forearm",
    "wrist": "hand", "palm": "hand",
    "finger": "fingers", "handtip": "fingers",
    "upperleg": "thigh", "leg": "thigh", "femur": "thigh",
    "lowerleg": "shin", "calf": "shin", "knee": "shin",
    "ankle": "foot", "toe": "foot",
    "skull": "head",
}
_SIDES = {"l": "l", "left": "l", "r": "r", "right": "r"}
JOINT_RE = re.compile(r"^j(\d{1,3})$", re.I)


def name_of(joint):
    """our name for a joint id; unknown ids keep the jNNN form"""
    return JOINTS[joint][0] if joint in JOINTS else f"j{joint:03d}"


def key(name):
    """'R_UpperArm' / 'upperarm.R' / 'upper_arm_right' / 'Right Upper Arm' -> 'r_upperarm' (side first, no
    separators in the rest); names without a side -> just the letters"""
    s = re.sub(r"\.\d{3}$", "", name.strip())                 # Blender's .001
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s).lower()       # camelCase -> camel_case
    parts = [p for p in re.split(r"[\s_.\-:|]+", s) if p]
    side = None
    if parts and parts[0] in _SIDES and len(parts) > 1:
        side = _SIDES[parts.pop(0)]
    elif parts and parts[-1] in _SIDES and len(parts) > 1:
        side = _SIDES[parts.pop()]
    rest = "".join(parts)
    return (side + "_" + rest) if side else rest


_BY_KEY = {}
for _j, (_n, _p) in JOINTS.items():
    _BY_KEY[key(_n)] = _j
for _alias, _ours in _ALIASES.items():
    for _side in ("l", "r", None):
        target = (_side + "_" + _ours) if _side else _ours
        if target in _BY_KEY:
            _BY_KEY.setdefault((_side + "_" + _alias) if _side else _alias, _BY_KEY[target])


def joint_of(name):
    """a standard joint's id from any of its names ('j013', 'l_upperarm', 'UpperArm.L', 'clavicle_r'...),
    else None (a custom bone)"""
    m = JOINT_RE.match(name.strip())
    if m:
        return int(m.group(1))
    return _BY_KEY.get(key(name))


if __name__ == "__main__":
    for j, (n, p) in sorted(JOINTS.items()):
        print(f"j{j:03d}  {n:16s} parent {name_of(p) if p is not None else '-'}")
