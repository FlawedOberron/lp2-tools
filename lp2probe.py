#!/usr/bin/env python3
"""Read Lost Planet 2's DLC / custom-part state from the running game (Proton, same user).

  lp2probe.py            finds LP2DX9.exe or LP2DX11.exe and prints DLC packages, the DLC
                         part table and which DLC part ids (180-249) are unlocked

Needs kernel.yama.ptrace_scope = 0 (it is on this machine). Read-only.
Addresses per build were mapped by diffing the unlock function (DX9 0x855c10, DX11 0x8652c0).
"""
import os, struct, sys

BUILDS = {  # exe: (DLC manager pointer, game object pointer)
    "LP2DX9.exe": (0x1842EB0, 0x1842020),
    "LP2DX11.exe": (0x1852F50, 0x18520C0),
}
MASKS = [("head", 0x50710), ("body", 0x50730), ("back", 0x50770), ("legs", 0x50750)]
TABLE = [("head", 0), ("body", 1), ("back", 2), ("legs", 3)]  # DLC table row = category - 1


def find_game():
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode("latin-1")
        except OSError:
            continue
        for exe in BUILDS:
            if cmd.startswith("Z:") and cmd.endswith(exe):
                return int(pid), exe
    return None, None


def main():
    pid, exe = find_game()
    if not pid:
        raise SystemExit("game not running")
    mem = open(f"/proc/{pid}/mem", "rb")

    def rd(a, n):
        mem.seek(a)
        return mem.read(n)

    u32 = lambda a: struct.unpack("<I", rd(a, 4))[0]
    mgr_p, game_p = BUILDS[exe]
    mgr, game = u32(mgr_p), u32(game_p)
    print(f"{exe} pid {pid}: DLC manager {mgr:#x}, game {game:#x}")
    npkg = struct.unpack("<i", rd(mgr + 0x20, 4))[0]
    print(f"packages: {npkg}")
    for i in range(max(0, min(npkg, 0x48))):
        title = u32(mgr + 0x538 + i * 0x20)
        path = rd(mgr + 0xF3A + i * 0x104, 0x104).split(b"\0")[0].decode("latin-1")
        print(f"  [{i}] title {title:#x} {path}")
    for cat, row in TABLE:
        tab = struct.unpack("<70i", rd(mgr + 0x40 + row * 70 * 4, 280))
        used = {n: p for n, p in enumerate(tab) if p != -1}
        words = struct.unpack("<8I", rd(game + dict(MASKS)[cat], 32))
        bit = lambda i: bool(words[i >> 5] & (0x80000000 >> (i & 31)))
        unlocked = [i - 180 for i in range(180, 250) if bit(i)]
        names = {n: rd(mgr + 0x8DBE + ((row * 70 + n) * 7 + 1) * 0x2C, 0x2C).split(b"\0")[0].decode("utf-8", "replace")
                 for n in used}
        print(f"{cat}: slots from packages {used or '-'}  unlocked DLC slots {unlocked or '-'}  names {names or '-'}")


if __name__ == "__main__":
    main()
