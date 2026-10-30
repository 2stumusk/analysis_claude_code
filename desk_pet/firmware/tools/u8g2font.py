"""Reads a u8g2 font (as LovyanGFX ships efontCN_12) for the desktop preview.

Only parses the C array as data: the font table is decoded here, nothing from
it is compiled or run. Format: u8g2's font header (23 bytes), an 8-bit glyph
list, then a unicode lookup table and 16-bit glyph list; each glyph is
run-length coded bits (see u8g2_font.c / LovyanGFX lgfx_fonts.cpp U8g2font).
"""

import re
ESC = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, "\\": 92, '"': 34, "'": 39, "?": 63}

def c_array(path, name):
    src = open(path, encoding="latin-1").read()
    start = src.index("const uint8_t %s[" % name)
    m = re.compile(r'\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', re.S).match(src, src.index("=", start) + 1)
    out = bytearray()
    for lit in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1), re.S):
        i = 0
        while i < len(lit):
            ch = lit[i]
            if ch != "\\":
                out.append(ord(ch)); i += 1; continue
            nxt = lit[i + 1]
            if nxt in "01234567":
                j = i + 1
                while j < len(lit) and j < i + 4 and lit[j] in "01234567":
                    j += 1
                out.append(int(lit[i + 1:j], 8) & 255); i = j
            elif nxt == "x":
                j = i + 2
                while j < len(lit) and lit[j] in "0123456789abcdefABCDEF":
                    j += 1
                out.append(int(lit[i + 2:j], 16) & 255); i = j
            else:
                out.append(ESC[nxt]); i += 2
    return bytes(out) + b"\0"  # the C literal's terminating NUL

class Bits:
    def __init__(self, data, pos):
        self.d, self.p, self.bit = data, pos, 0
    def u(self, n):
        v = 0; got = 0
        while got < n:
            byte = self.d[self.p]
            take = min(8 - self.bit, n - got)
            v |= ((byte >> self.bit) & ((1 << take) - 1)) << got
            got += take; self.bit += take
            if self.bit == 8: self.bit = 0; self.p += 1
        return v
    def s(self, n):
        return self.u(n) - (1 << (n - 1))

class U8g2Font:
    """Glyph metrics and pixels by code point."""

    def __init__(self, data):
        self.f = data
        h = data
        self.cnt, self.bbx, self.b0, self.b1, self.bw, self.bh, self.bx, self.by, self.bd = h[0:9]
        self.maxw, self.maxh = h[9], h[10]
        sb = lambda v: v - 256 if v > 127 else v
        self.xoff, self.yoff = sb(h[11]), sb(h[12])
        self.upper = h[17] << 8 | h[18]; self.lower = h[19] << 8 | h[20]; self.uni = h[21] << 8 | h[22]
        self.cache = {}
    def glyph_pos(self, enc):
        f = self.f; base = 23
        if enc <= 255:
            p = base + (self.lower if enc >= ord("a") else self.upper if enc >= ord("A") else 0)
            while f[p + 1]:
                if f[p] == enc: return p + 2
                p += f[p + 1]
            return None
        p = base + self.uni; lut = p
        while True:
            p += (f[lut] << 8) + f[lut + 1]
            e = (f[lut + 2] << 8) + f[lut + 3]
            lut += 4
            if e >= enc: break
        while True:
            e = (f[p] << 8) + f[p + 1]
            if e == 0: return None
            if e == enc: return p + 3
            p += f[p + 2]
    def glyph(self, cp):
        if cp in self.cache: return self.cache[cp]
        pos = self.glyph_pos(cp) if cp < 0x10000 else None
        if pos is None:
            self.cache[cp] = None; return None
        b = Bits(self.f, pos)
        w, h = b.u(self.bw), b.u(self.bh)
        x, y, adv = b.s(self.bx), b.s(self.by), b.s(self.bd)
        pix = []
        lx = ly = 0; total = w * h; done = 0
        while done < total:
            a, o = b.u(self.b0), b.u(self.b1)
            while True:
                for val, n in ((0, a), (1, o)):
                    for _ in range(n):
                        if val: pix.append((lx, ly))
                        lx += 1; done += 1
                        if lx == w: lx = 0; ly += 1
                if done >= total or b.u(1) == 0: break
        g = (w, h, x, y, adv, pix)
        self.cache[cp] = g
        return g
