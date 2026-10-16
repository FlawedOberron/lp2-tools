#!/usr/bin/env python3
"""Byte-value scanner for the running game that keeps one bit per byte instead of an address list,
so a first scan matching ~1e9 bytes costs ~150 MB rather than ~8 GB (see memscan.py for 2/4-byte
values and small candidate sets).

  membits.py new VALUE        bytes equal to VALUE, in every writable mapping below 4 GB
  membits.py next VALUE       keep the candidates that now equal VALUE
  membits.py show [N]         count, and print the first N (default 50) addresses with values

State: $MEMBITS_STATE (default ~/.cache/lp2-membits.npz). Read-only on the game.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memscan import game_pid, regions  # noqa: E402

STATE = os.environ.get("MEMBITS_STATE", os.path.expanduser("~/.cache/lp2-membits.npz"))


def read(mem, lo, hi):
    try:
        mem.seek(lo)
        return np.frombuffer(mem.read(hi - lo), dtype=np.uint8)
    except OSError:
        return None


def save(pid, masks):
    los = np.array(sorted(masks), dtype=np.uint64)
    np.savez(STATE, pid=pid, los=los, lens=np.array([masks[int(l)][1] for l in los], dtype=np.uint64),
             **{f"m{i}": masks[int(l)][0] for i, l in enumerate(los)})


def load():
    st = np.load(STATE)
    return int(st["pid"]), {int(l): (st[f"m{i}"], int(n)) for i, (l, n) in enumerate(zip(st["los"], st["lens"]))}


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    pid = game_pid()
    mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
    if a[0] == "new":
        val = int(a[1], 0)
        masks, total = {}, 0
        for lo, hi in regions(pid):
            arr = read(mem, lo, hi)
            if arr is None or not len(arr):
                continue
            m = arr == val
            n = int(m.sum())
            if n:
                masks[lo] = (np.packbits(m), len(arr))
                total += n
        save(pid, masks)
        print(f"{total} candidates")
    elif a[0] == "next":
        val = int(a[1], 0)
        spid, masks = load()
        if spid != pid:
            raise SystemExit("game restarted since 'new'; start again")
        out, total = {}, 0
        for lo, (bits, n) in masks.items():
            arr = read(mem, lo, lo + n)
            if arr is None or not len(arr):
                continue
            m = np.unpackbits(bits, count=n)[:len(arr)].astype(bool) & (arr == val)
            k = int(m.sum())
            if k:
                out[lo] = (np.packbits(m), len(m))
                total += k
        save(pid, out)
        print(f"{total} candidates")
    elif a[0] == "show":
        limit = int(a[1]) if len(a) > 1 else 50
        _, masks = load()
        total, shown = 0, 0
        for lo, (bits, n) in sorted(masks.items()):
            idx = np.nonzero(np.unpackbits(bits, count=n))[0]
            total += len(idx)
            for i in idx:
                if shown < limit:
                    mem.seek(lo + int(i))
                    print(f"{lo + int(i):#010x} = {mem.read(1)[0]}")
                    shown += 1
        print(f"({total} total)")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
