#!/usr/bin/env python3
"""Lost Planet 2 PC save (Lostplanet2.Lostplanet2Save-capcom): decode / encode.

  lp2save.py decode SAVE OUT.bin       write the plain 0x5000-byte data
  lp2save.py encode IN.bin SAVE        write a save the game accepts (fresh SHA-1 header)
  lp2save.py check SAVE                verify the header

Format (from the DX9 save writer FUN_00858850 and its crypto at 0x7a4720-0x7a4e30):
  0x00  20 bytes  SHA-1 of the PLAIN data, written as five little-endian words
                  (the exe masks its SHA-1 constants with ^0xbeeff00d / ^0xbadface, but they
                  are the standard ones)
  0x14  u32       0x77cec928 (magic)
  0x18  u32       0
  0x1c  u32       0x1000
  0x20  0x5000    plain data XOR 0x73 ('s', first byte of the key string "shiorasikunai")
The plain data is ~10 sections serialised back to back (order table at DX9 0x173b1b8).
"""
import hashlib, struct, sys

MAGIC, KEY = 0x77CEC928, 0x73
BODY = 0x5000


def digest(plain):
    words = struct.unpack(">5I", hashlib.sha1(plain).digest())
    return struct.pack("<5I", *words)


def decode(raw):
    if len(raw) != 0x20 + BODY:
        raise ValueError(f"unexpected size {len(raw)}")
    if struct.unpack_from("<I", raw, 0x14)[0] != MAGIC:
        raise ValueError("bad magic")
    plain = bytes(b ^ KEY for b in raw[0x20:])
    return plain, digest(plain) == raw[:0x14]


def encode(plain, tail=None):
    if len(plain) != BODY:
        raise ValueError(f"plain data must be {BODY:#x} bytes")
    tail = tail or struct.pack("<III", MAGIC, 0, 0x1000)
    return digest(plain) + tail + bytes(b ^ KEY for b in plain)


def main():
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "decode":
        plain, ok = decode(open(a[1], "rb").read())
        open(a[2], "wb").write(plain)
        print(f"wrote {a[2]} (header {'valid' if ok else 'INVALID'})")
    elif len(a) == 3 and a[0] == "encode":
        open(a[2], "wb").write(encode(open(a[1], "rb").read()))
        print(f"wrote {a[2]}")
    elif len(a) == 2 and a[0] == "check":
        print("valid" if decode(open(a[1], "rb").read())[1] else "INVALID")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
