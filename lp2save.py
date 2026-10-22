#!/usr/bin/env python3
"""Lost Planet 2 PC save (Lostplanet2.Lostplanet2Save-capcom): decode / encode.

  lp2save.py decode SAVE OUT.bin       write the plain 0x5000-byte data
  lp2save.py encode IN.bin SAVE        write a save the game accepts (fresh SHA-1 header)
  lp2save.py check SAVE                verify the header
  lp2save.py convert IN SAVE           any LP2 save (GFWL-era protected files too) -> the current format

Format (from the DX9 save writer FUN_00858850 and its crypto at 0x7a4720-0x7a4e30):
  0x00  20 bytes  SHA-1 of the PLAIN data, written as five little-endian words
                  (the exe masks its SHA-1 constants with ^0xbeeff00d / ^0xbadface, but they
                  are the standard ones)
  0x14  u32       0x77cec928 (magic)
  0x18  u32       0
  0x1c  u32       0x1000
  0x20  0x5000    plain data XOR 0x73 ('s', first byte of the key string "shiorasikunai")
The plain data is 10 sections serialised back to back. Each save picks one of 4 orders at random
(xorshift, DX9 0x42acf0); header +0x18 = the order index into the table at DX9 0x173b1b8 (orders below).
Section sizes (from the readers): 0 0x50, 1 0x2cc, 2 0x20, 3 0x2e4, 4 0x84, 5 0x770, 6 0x10,
7 0x2f50 ('u32 0x74000, u32 sum of the record words', checksummed), 8 = its own first u32 (4 when 0), 9 empty.
Header +0x1c = 0x1000 (version). The reader checks the SHA-1, the magic and the order index.
GFWL-era files: the game passes the 0x5020 bytes through XLiveProtectData, which under real GFWL put
0x168 bytes in front (u32 0x128, ..., an encrypted copy of the header) and left the 0x5000 data as it was.
Our xlive.dll passes them through unchanged, so `convert` (and the dll on load) takes the file's last 0x5000
bytes, finds the order whose layout puts a valid section 7 in place and writes a fresh header.
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


ORDERS = [[9, 3, 5, 7, 6, 2, 1, 8, 4, 0], [9, 6, 8, 7, 5, 4, 1, 2, 0, 3],
          [9, 4, 7, 5, 3, 8, 2, 0, 6, 1], [9, 2, 4, 1, 5, 3, 8, 6, 0, 7]]
SIZES = {0: 0x50, 1: 0x2CC, 2: 0x20, 3: 0x2E4, 4: 0x84, 5: 0x770, 6: 0x10, 7: 0x2F50, 9: 0}


def find_order(plain):
    """The order index whose layout puts a checksum-valid section 7 where it belongs, else None."""
    for idx, order in enumerate(ORDERS):
        o = 0
        for sec in order:
            if sec == 7:
                if o + 0x2F50 <= len(plain) and struct.unpack_from("<I", plain, o)[0] == 0x74000:
                    words = struct.unpack_from("<%dI" % ((0x2E50 + 0xE8) // 4), plain, o + 16)
                    if sum(words) & 0xFFFFFFFF == struct.unpack_from("<I", plain, o + 4)[0]:
                        return idx
                break
            o += SIZES[sec] if sec != 8 else max(4, struct.unpack_from("<I", plain, o)[0])
            if o > len(plain):
                break
    return None


def convert(raw):
    """Any LP2 save file -> (current-format file, order index); the body is the file's last 0x5000 bytes."""
    if len(raw) < 0x20 + BODY:
        raise ValueError(f"too small for an LP2 save ({len(raw)} bytes)")
    plain = bytes(b ^ KEY for b in raw[-BODY:])
    idx = find_order(plain)
    if idx is None:
        raise ValueError("no section order fits: not an LP2 save, or a layout this tool does not know")
    return encode(plain, struct.pack("<III", MAGIC, idx, 0x1000)), idx


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
    elif a[0] == "convert" and len(a) == 3:
        raw = open(a[1], "rb").read()
        out, idx = convert(raw)
        open(a[2], "wb").write(out)
        print(f"wrote {a[2]} ({len(raw)} -> {len(out)} bytes, section order {idx})")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
