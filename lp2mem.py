#!/usr/bin/env python3
"""Lost Planet 2 memory while it runs (Linux / Proton): the 32-bit address space it uses, against the Windows 2 GB
and Proton 4 GB limits.

  lp2mem.py            one reading
  lp2mem.py -w [CSV]   a reading every 2 s until the game exits (and a CSV log), then the peak

used     every mapping below 4 GB: what counts against the limit (reserved and committed; the Wine / Proton
         libraries are in it too, roughly as Windows' own DLLs would be)
resident what is in RAM now
gap      the largest free block left (big allocations, like a map's textures, need one piece)
"""
import os, sys, time

GB = 1 << 30


def find():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                c = open(f"/proc/{p}/comm").read().strip()
            except OSError:
                continue
            if c in ("LP2DX9.exe", "LP2DX11.exe"):
                return int(p), c
    return None, None


def reading(pid):
    spans = []
    for line in open(f"/proc/{pid}/maps"):
        a, b = (int(x, 16) for x in line.split()[0].split("-"))
        if a < 1 << 32:
            spans.append((a, min(b, 1 << 32)))
    spans.sort()
    used = sum(b - a for a, b in spans)
    gap, prev = 0, 0x10000
    for a, b in spans:
        gap = max(gap, a - prev)
        prev = max(prev, b)
    gap = max(gap, (1 << 32) - prev)
    rss = 0
    for line in open(f"/proc/{pid}/status"):
        if line.startswith("VmRSS:"):
            rss = int(line.split()[1]) * 1024
    return used, rss, gap


def fmt(used, rss, gap):
    return (f"used {used / GB:.2f} GB ({used / (2 * GB):.0%} of Windows' 2 GB, {used / (4 * GB):.0%} of 4 GB)  "
            f"resident {rss / GB:.2f} GB  largest gap {gap / (1 << 20):.0f} MB")


def main():
    pid, name = find()
    if not pid:
        raise SystemExit("Lost Planet 2 is not running")
    if "-w" not in sys.argv:
        print(name, fmt(*reading(pid)))
        return
    rest = [a for a in sys.argv[1:] if a != "-w"]
    log = open(rest[0], "a") if rest else None
    peak = (0, 0, 0)
    try:
        while os.path.exists(f"/proc/{pid}"):
            try:
                r = reading(pid)
            except OSError:
                break
            peak = max(peak, r)
            print("\r" + time.strftime("%H:%M:%S ") + fmt(*r) + "   ", end="", flush=True)
            if log:
                log.write(f"{time.time():.0f},{r[0]},{r[1]},{r[2]}\n")
                log.flush()
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    print("\npeak " + fmt(*peak))


if __name__ == "__main__":
    main()
