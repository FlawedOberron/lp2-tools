#!/usr/bin/env python3
"""Hardware read/write watchpoints on the running game (ptrace + x86 debug registers).

  hwwatch.py SECONDS ADDR [ADDR ...]      up to 4 addresses per run (1-byte watches)
  hwwatch.py --batch SECONDS FILE         addresses from FILE, 4 at a time
  hwwatch.py --exec SECONDS ADDR [...]    execution breakpoints: count how often code runs
  hwwatch.py --write SECONDS ADDR [...]   write-only watchpoints
  options before the mode: --ecx (with HWREG=n to report a register, HWREG=-1 for the stack)

Prints each distinct (address, instruction) pair that touched a watched byte. The game is never
paused for long; debug registers are cleared again on exit. Needs ptrace_scope 0.
"""
import ctypes, ctypes.util, os, re, signal, struct, sys, time

# Always stop through KeyboardInterrupt so the debug registers get cleared, even when started from
# a background shell (which ignores SIGINT) or stopped with SIGTERM.
def _stop(signum, frame):
    raise KeyboardInterrupt
signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.ptrace.restype = ctypes.c_long
libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
PTRACE_PEEKUSER, PTRACE_POKEUSER, PTRACE_CONT, PTRACE_DETACH = 3, 6, 7, 17
PTRACE_GETREGS, PTRACE_SETREGS, PTRACE_SEIZE, PTRACE_INTERRUPT = 12, 13, 0x4206, 0x4207
EFLAGS_IDX = 18
EXEC = False
WRITE = False
SEQ = os.environ.get("HWSEQ") == "1"  # print every hit as it happens, with the watched dword after it
SHOW_ECX = False
REG_IDX = int(os.environ.get("HWREG", "11"))  # user_regs_struct index: 11 rcx, 13 rsi, 14 rdi, 4 rbp, 5 rbx
DR_OFF = 848  # offsetof(struct user, u_debugreg) on x86_64
RIP_IDX = 16  # user_regs_struct index of rip
WALL = 0x40000000


def ptrace(req, tid, addr=0, data=0):
    r = libc.ptrace(req, tid, ctypes.c_void_p(addr), ctypes.c_void_p(data))
    if r == -1 and ctypes.get_errno():
        raise OSError(ctypes.get_errno(), f"ptrace {req} tid {tid}")
    return r


def game_pid():
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode("latin-1")
        except OSError:
            continue
        if re.match(r"Z:.*\\LP2DX(9|11)\.exe$", cmd):
            return int(pid)
    raise SystemExit("game not running")


def waitstop(tid):
    st = ctypes.c_int()
    while True:
        r = libc.waitpid(tid, ctypes.byref(st), WALL)
        if r == tid:
            return st.value


def rip(tid):
    regs = (ctypes.c_ulonglong * 27)()
    ptrace(PTRACE_GETREGS, tid, 0, ctypes.addressof(regs))
    return regs[RIP_IDX]


def set_dr(tid, addrs):
    dr7 = 0
    for i, a in enumerate(addrs):
        ptrace(PTRACE_POKEUSER, tid, DR_OFF + 8 * i, a)
        dr7 |= (1 << (2 * i)) | ((0b00 if EXEC else 0b01 if WRITE else 0b11) << (16 + 4 * i))  # local enable, exec or read/write, 1 byte
    ptrace(PTRACE_POKEUSER, tid, DR_OFF + 8 * 7, dr7)


def attach_new(pid, addrs, attached):
    for t in (int(x) for x in os.listdir(f"/proc/{pid}/task")):
        if t in attached:
            continue
        try:
            ptrace(PTRACE_SEIZE, t)
            ptrace(PTRACE_INTERRUPT, t)
            waitstop(t)
            set_dr(t, addrs)
            ptrace(PTRACE_CONT, t)
            attached.append(t)
        except OSError:
            pass


def watch(pid, addrs, seconds):
    attached = []
    attach_new(pid, addrs, attached)
    hits = {}
    end = time.time() + seconds
    st = ctypes.c_int()
    rescan = time.time() + 0.5
    try:
        while time.time() < end:
            if time.time() > rescan:  # threads the game starts later need the registers too
                attach_new(pid, addrs, attached)
                rescan = time.time() + 0.5
            t = libc.waitpid(-1, ctypes.byref(st), WALL | 1)  # WNOHANG
            if t <= 0:
                time.sleep(0.001)
                continue
            s = st.value
            if not os.WIFSTOPPED(s):
                continue
            sig = os.WSTOPSIG(s)
            if sig == signal.SIGTRAP and (s >> 16) == 0:
                dr6 = ptrace(PTRACE_PEEKUSER, t, DR_OFF + 8 * 6) & 0xF
                regs = (ctypes.c_ulonglong * 27)()
                ptrace(PTRACE_GETREGS, t, 0, ctypes.addressof(regs))
                if SHOW_ECX and REG_IDX < 0:  # return address and first stack args at function entry
                    sp = regs[19] & 0xFFFFFFFF
                    with open(f"/proc/{pid}/mem", "rb") as mm:
                        mm.seek(sp)
                        nw = int(os.environ.get("HWSTACK", "4"))
                        words = struct.unpack(f"<{nw}I", mm.read(4 * nw))
                    ip = (regs[RIP_IDX], words)
                else:
                    ip = regs[RIP_IDX] if not SHOW_ECX else (regs[RIP_IDX], regs[REG_IDX] & 0xFFFFFFFF)
                for i in range(len(addrs)):
                    if dr6 & (1 << i) and SEQ:
                        with open(f"/proc/{pid}/mem", "rb") as mm:
                            mm.seek(addrs[i] & ~3)
                            val = struct.unpack("<I", mm.read(4))[0]
                        eip = ip[0] if isinstance(ip, tuple) else ip
                        extra = (" stack " + " ".join(f"{w:#010x}" for w in ip[1])) if isinstance(ip, tuple) and isinstance(ip[1], tuple) else ""
                        print(f"{time.strftime('%T')} {addrs[i]:#010x} eip {eip:#010x} value {val:#010x}{extra}", flush=True)
                    if dr6 & (1 << i):
                        k = (addrs[i], ip)
                        hits[k] = hits.get(k, 0) + 1
                ptrace(PTRACE_POKEUSER, t, DR_OFF + 8 * 6, 0)
                if EXEC:  # resume flag, so the breakpoint does not fire again on the same instruction
                    regs = (ctypes.c_ulonglong * 27)()
                    ptrace(PTRACE_GETREGS, t, 0, ctypes.addressof(regs))
                    regs[EFLAGS_IDX] |= 0x10000
                    ptrace(PTRACE_SETREGS, t, 0, ctypes.addressof(regs))
                ptrace(PTRACE_CONT, t, 0, 0)
            elif (s >> 16) != 0:
                ptrace(PTRACE_CONT, t, 0, 0)  # ptrace event stop
            else:
                ptrace(PTRACE_CONT, t, 0, sig)  # pass the game's own signals on
    finally:
        for t in attached:
            try:
                ptrace(PTRACE_INTERRUPT, t)
                s = waitstop(t)
                ptrace(PTRACE_POKEUSER, t, DR_OFF + 8 * 7, 0)
                ptrace(PTRACE_DETACH, t, 0, 0)
            except OSError:
                pass
    return hits


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    global EXEC, SHOW_ECX, WRITE
    pid = game_pid()
    if a[0] == "--ecx":
        SHOW_ECX = True
        a = a[1:]
    if a[0] == "--write":
        WRITE = True
        a = a[1:]
    if a[0] == "--exec":
        EXEC = True
        a = a[1:]
    if a[0] == "--batch":
        secs = float(a[1])
        addrs = [int(x, 16) for x in open(a[2]).read().split()]
    else:
        secs = float(a[0])
        addrs = [int(x, 16) for x in a[1:]]
    for i in range(0, len(addrs), 4):
        group = addrs[i:i + 4]
        hits = watch(pid, group, secs)
        for (addr, ip), n in sorted(hits.items()):
            if SHOW_ECX and REG_IDX < 0:
                print(f"{addr:#010x} at eip {ip[0]:#010x} stack " + " ".join(f"{w:#010x}" for w in ip[1]) + f" x{n}", flush=True)
            elif SHOW_ECX:
                print(f"{addr:#010x} at eip {ip[0]:#010x} ecx {ip[1]:#010x} x{n}", flush=True)
            else:
                print(f"{addr:#010x} touched by eip {ip:#010x} x{n}", flush=True)
        if not hits:
            print("quiet:", " ".join(f"{x:#010x}" for x in group), flush=True)


if __name__ == "__main__":
    main()
