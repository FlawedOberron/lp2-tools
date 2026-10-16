#!/usr/bin/env python3
"""Map the game's pad action bits: speaks one action at a time (espeak-ng + a desktop notification)
and logs which pad bits turn on while the player performs it. Read-only on the game.

  padmap.py [--gap SECONDS] [--start N] OUT.txt

Pad object: *(0x1852080 + 4 * local player index) in LP2DX11.exe; +0x3b8 = held bits,
+0x3c0 = pressed-this-frame bits (zoom = 0x100000 in both). A wider window (+0x380..+0x400) is
logged in case some actions live elsewhere. Press F10 (or nothing) when you don't know a binding.
"""
import argparse, os, struct, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memscan import game_pid  # noqa: E402

ACTIONS = ["fire", "throw grenade", "zoom", "jump", "crouch", "reload", "melee attack", "grapple",
           "action, pick up or interact", "next weapon", "previous weapon", "switch grenade",
           "use T-ENG", "gesture or taunt", "quick turn", "dodge or roll", "map or scoreboard",
           "chat or voice", "walk forward", "walk back", "strafe left", "strafe right"]
VS_ACTIONS = ["fire main weapon", "fire second weapon or right click", "zoom", "jump or boost", "dash",
              "crouch or brake", "reload", "action or get out", "switch seat or weapon", "next weapon",
              "use T-ENG", "melee or ram", "quick turn", "lock on", "map or scoreboard"]
PADS, LO, HI = 0x1852080, 0x380, 0x400


def say(text):
    subprocess.Popen(["notify-send", "-t", "3000", "LP2 controls", text], stderr=subprocess.DEVNULL)
    subprocess.Popen(["espeak-ng", "-s", "150", text], stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=6.0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--vs", action="store_true", help="vehicle (VS) controls instead of on foot")
    ap.add_argument("out")
    a = ap.parse_args()
    pid = game_pid()
    mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
    mem.seek(PADS)
    pad = struct.unpack("<I", mem.read(4))[0]
    log = open(a.out, "w")
    log.write(f"# pad {pad:#x}, window +{LO:#x}..+{HI:#x}\n")
    stop = threading.Event()
    t0 = time.time()

    def poll():
        last = None
        while not stop.is_set():
            mem.seek(pad + LO)
            d = struct.unpack(f"<{(HI - LO) // 4}I", mem.read(HI - LO))
            if d != last:
                if last is not None:
                    ch = [f"+{LO + 4 * i:#x}:{last[i]:08x}->{v:08x}" for i, v in enumerate(d) if v != last[i]]
                    log.write(f"{time.time() - t0:8.2f} {' '.join(ch)}\n")
                    log.flush()
                last = d
            time.sleep(0.004)

    th = threading.Thread(target=poll, daemon=True)
    th.start()
    say("Controls mapping starting. Do each action once when you hear it.")
    time.sleep(4)
    for i, act in enumerate((VS_ACTIONS if a.vs else ACTIONS)[a.start:], a.start):
        log.write(f"{time.time() - t0:8.2f} PROMPT {i} {act}\n")
        log.flush()
        say(act)
        time.sleep(a.gap)
    say("Done, thanks")
    time.sleep(1)
    stop.set()
    th.join()
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
