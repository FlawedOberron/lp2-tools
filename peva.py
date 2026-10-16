"""Tiny PE helper: map VAs of the unpacked LP2 exe to file bytes."""
import struct


class PE:
    def __init__(self, path):
        self.b = b = open(path, "rb").read()
        pe = struct.unpack_from("<I", b, 0x3C)[0]
        ns, osz = struct.unpack_from("<H", b, pe + 6)[0], struct.unpack_from("<H", b, pe + 20)[0]
        self.base = struct.unpack_from("<I", b, pe + 24 + 28)[0]
        self.secs = []
        for i in range(ns):
            o = pe + 24 + osz + 40 * i
            vs, va, rs, ra = struct.unpack_from("<IIII", b, o + 8)
            self.secs.append((b[o:o + 8].rstrip(b"\0").decode(), va, vs, ra, rs))

    def off(self, va):
        r = va - self.base
        for _, sva, vs, ra, rs in self.secs:
            if sva <= r < sva + rs:
                return ra + r - sva
        return None  # unmapped or zero-filled (.bss)

    def u32(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from("<I", self.b, o)[0]

    def u8(self, va):
        o = self.off(va)
        return None if o is None else self.b[o]

    def cstr(self, va):
        o = self.off(va)
        return None if o is None else self.b[o:self.b.index(b"\0", o)].decode("latin1")
