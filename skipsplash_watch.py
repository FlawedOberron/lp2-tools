#!/usr/bin/env python3
"""Proof of concept for the splash-skip mod: patch the running game from outside.

  skipsplash_watch.py [timeout_seconds]

Waits for LP2DX9.exe / LP2DX11.exe, waits until SteamStub has decrypted .text (the patch site
matches the expected bytes), then NOPs the 'JZ show_logos' in the boot-logo state machine
(DX11 FUN_008acfb0 state 0), so state 0 always jumps to state 6 (logos done -> title).
The real mod does the same from inside our xlive.dll on the first xlive call.
"""
import os, re, sys, time

SITES = {"LP2DX11.exe": 0x8AD03F, "LP2DX9.exe": 0x89D88F}
# mov ecx,[abs]; cmp byte [ecx+0x1829],0; jz rel32; pop edi; mov byte [esi+4],6
SIG = re.compile(rb"\x8b\x0d....\x80\xb9\x29\x18\x00\x00\x00\x0f\x84....\x5f\xc6\x46\x04\x06", re.S)
JZ, NOPS = bytes.fromhex("0f84ec000000"), b"\x90" * 6


def find_game(ignore=()):
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) in ignore:
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode("latin-1")
        except OSError:
            continue
        for exe in SITES:
            if cmd.startswith("Z:") and cmd.endswith(exe):
                return int(pid), exe
    return None, None


def main():
    deadline = time.time() + (float(sys.argv[1]) if len(sys.argv) > 1 else 600)
    already, _ = find_game()  # a session that is already running is past its logos
    pid = None
    while time.time() < deadline:
        pid, exe = find_game(ignore={already})
        if pid:
            break
        time.sleep(0.05)
    if not pid:
        raise SystemExit("game did not start")
    site = SITES[exe]
    print(f"{exe} pid {pid}, waiting for decrypted code at {site:#x}", flush=True)
    while time.time() < deadline:
        try:
            with open(f"/proc/{pid}/mem", "r+b", buffering=0) as mem:
                mem.seek(site - 13)
                window = mem.read(24)
                if SIG.fullmatch(window) and window[13:19] == JZ:
                    mem.seek(site)
                    mem.write(NOPS)
                    mem.seek(site)
                    print(f"patched at {time.strftime('%T')}: now {mem.read(6).hex()}", flush=True)
                    return
                if window[13:19] == NOPS:
                    print("already patched")
                    return
        except OSError:
            pass  # image not mapped yet
        time.sleep(0.01)
    raise SystemExit("code never decrypted / signature not found")


if __name__ == "__main__":
    main()
