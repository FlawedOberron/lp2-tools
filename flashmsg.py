#!/usr/bin/env python3
"""rFlashMessage (message\\msgPC\\*.rFlashMessage) reader and editor.

  flashmsg.py FILE [REGEX]                  print 'block id: text' (all, or matching REGEX)
  flashmsg.py set FILE OUT ID TEXT          replace message ID in every language block

Layout (all little-endian):
  'MES\\0'  u32 12 (version)  u32 name length  name + '\\0'
  then blocks to the end of the file: u32 language id, u32 count, count x (u32 length, UTF-8
  text, '\\0'). MsgOnline has 12 blocks with language ids 0-6, 10, 11, 17, 18, 19; block 1
  (id 1) is English.
"""
import re, struct, sys


def parse(b):
    if b[:4] != b"MES\0":
        raise ValueError("not an rFlashMessage")
    ver, nlen = struct.unpack_from("<II", b, 4)
    o = 12 + nlen + 1
    head, blocks = b[:o], []
    while o < len(b):
        lang, n = struct.unpack_from("<II", b, o)
        o += 8
        texts = []
        for _ in range(n):
            ln = struct.unpack_from("<I", b, o)[0]
            texts.append(b[o + 4:o + 4 + ln])
            o += 4 + ln + 1
        blocks.append((lang, texts))
    return head, blocks


def build(head, blocks):
    out = bytearray(head)
    for lang, texts in blocks:
        out += struct.pack("<II", lang, len(texts))
        for t in texts:
            out += struct.pack("<I", len(t)) + t + b"\0"
    return bytes(out)


def read(path):
    return [[t.decode("utf-8", "replace") for t in texts] for _, texts in parse(open(path, "rb").read())[1]]


def set_message(data, index, text):
    head, blocks = parse(data)
    for _, texts in blocks:
        texts[index] = text.encode("utf-8")
    return build(head, blocks)


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "set":
        data = open(sys.argv[2], "rb").read()
        open(sys.argv[3], "wb").write(set_message(data, int(sys.argv[4]), sys.argv[5]))
        sys.exit()
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    langs = read(sys.argv[1])
    pat = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
    for li, lang in enumerate(langs):
        for i, t in enumerate(lang):
            if not pat or pat.search(t):
                print(f"{li} {i}: {t!r}")
