#!/usr/bin/env python3
"""Narrow down where the running game keeps a value (like a cheat-engine 'next scan').

  memscan.py new VALUE [--size 1|2|4]   snapshot every writable mapping below 4 GB
  memscan.py next VALUE                 keep the candidates that now hold VALUE
  memscan.py show                       list the remaining candidates

Candidates live in $MEMSCAN_STATE (default ~/.cache/lp2-memscan.npz). Read-only on the game.
"""
import os, re, sys
import numpy as np

STATE = os.environ.get("MEMSCAN_STATE", os.path.expanduser("~/.cache/lp2-memscan.npz"))
DT = {1: np.uint8, 2: np.uint16, 4: np.uint32}


def game_pid():
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode("latin-1")
        except OSError:
            continue
        if re.match(r"Z:.*\\LP2DX(9|11)\.exe$", cmd):
            return int(pid)
    raise SystemExit("game not running")


def regions(pid):
    for line in open(f"/proc/{pid}/maps"):
        addr, perms = line.split()[:2]
        lo, hi = (int(x, 16) for x in addr.split("-"))
        if "w" in perms and "r" in perms and hi <= 1 << 32 and hi - lo <= 512 << 20:
            yield lo, hi


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    pid = game_pid()
    mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
    if a[0] == "new":
        size = int(a[a.index("--size") + 1]) if "--size" in a else 4
        val = int(a[1], 0)
        found = []
        for lo, hi in regions(pid):
            try:
                mem.seek(lo)
                buf = mem.read(hi - lo)
            except OSError:
                continue
            arr = np.frombuffer(buf[: len(buf) // size * size], dtype=DT[size])
            idx = np.nonzero(arr == val)[0]
            found.append(lo + idx.astype(np.uint64) * size)
        cand = np.concatenate(found) if found else np.zeros(0, np.uint64)
        np.savez(STATE, cand=cand, size=size, pid=pid)
        print(f"{len(cand)} candidates")
        return
    st = np.load(STATE)
    cand, size = st["cand"], int(st["size"])
    if int(st["pid"]) != pid:
        raise SystemExit("game restarted since 'new'; start again")
    if a[0] == "next":
        val = int(a[1], 0)
        keep = []
        # read page by page so millions of candidates stay quick
        pages = cand // 4096 if len(cand) < 200000 else np.zeros(1, np.uint64)
        for page in np.unique(pages):
            sel = cand[pages == page] if len(cand) < 200000 else None
            if sel is None:
                break
            try:
                mem.seek(int(page) * 4096)
                buf = mem.read(4096 + 8)
            except OSError:
                continue
            for c in sel:
                o = int(c) - int(page) * 4096
                if int.from_bytes(buf[o:o + size], "little") == val:
                    keep.append(int(c))
        else:
            cand = np.array(keep, dtype=np.uint64)
            np.savez(STATE, cand=cand, size=size, pid=pid)
            print(f"{len(cand)} candidates")
            return
        # large set: re-read whole regions
        keep = []
        for lo, hi in regions(pid):
            # candidates are in address order: slice instead of masking all of them per region
            i, j = np.searchsorted(cand, [lo, hi])
            sel = cand[i:j]
            if not len(sel):
                continue
            try:
                mem.seek(lo)
                buf = mem.read(hi - lo)
            except OSError:
                continue
            arr = np.frombuffer(buf[: len(buf) // size * size], dtype=DT[size])
            rel = ((sel - lo) // size).astype(np.int64)
            sel, rel = sel[rel < len(arr)], rel[rel < len(arr)]  # short read: drop what we could not see
            ok = arr[rel] == val
            keep.append(sel[ok])
        cand = np.concatenate(keep) if keep else np.zeros(0, np.uint64)
        np.savez(STATE, cand=cand, size=size, pid=pid)
        print(f"{len(cand)} candidates")
    elif a[0] == "show":
        for c in cand[:200]:
            mem.seek(int(c))
            print(f"{int(c):#010x} = {int.from_bytes(mem.read(size), 'little')}")
        print(f"({len(cand)} total)")


if __name__ == "__main__":
    main()
