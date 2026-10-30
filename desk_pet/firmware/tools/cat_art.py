#!/usr/bin/env python3
"""The "cat" skin: an original 32x32 pixel cat, drawn here with a few shapes
and generated into the firmware (src/cat_art.h) and the web simulator
(web/cat_art.js), so both show exactly the same pixels.

    python3 firmware/tools/cat_art.py            regenerate both files
    python3 firmware/tools/cat_art.py --png DIR  also write enlarged PNGs to look at

White fur with orange patches. Each pose is a frame; the UI picks frames per
agent state and draws the extras (thought dots, "!", hearts, zzz) around it.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE = os.path.dirname(HERE)
ROOT = os.path.dirname(FIRMWARE)
SIZE = 32

# Index 0 is transparent. Hex digits in the frame rows.
PALETTE = [
    None,       # 0 transparent
    0x2B2230,   # 1 outline
    0xF7F3EE,   # 2 fur
    0xD8D0C8,   # 3 fur shade
    0xF2A65A,   # 4 orange patch
    0xC8783A,   # 5 orange shade
    0xFF9FB0,   # 6 pink: nose, inner ears, cheeks
    0x1C1C24,   # 7 eye
    0xFFFFFF,   # 8 eye highlight
    0xFF5D7A,   # 9 heart / tongue
    0x9AA3B2,   # a laptop
    0x5A6170,   # b laptop shade
    0x7EE0FF,   # c laptop logo glow
    0x5FA8FF,   # d book cover
    0xFFF4D6,   # e book pages
    0x3B6FB8,   # f book shade
]
O, FUR, SHADE, PATCH, PATCH2, PINK, EYE, HI = 1, 2, 3, 4, 5, 6, 7, 8
LAPTOP, LAPTOP2, GLOW, BOOK, PAGE, BOOK2 = 10, 11, 12, 13, 14, 15


class Canvas:
    def __init__(self):
        self.px = [[0] * SIZE for _ in range(SIZE)]

    def set(self, x, y, c):
        if 0 <= x < SIZE and 0 <= y < SIZE:
            self.px[y][x] = c

    def get(self, x, y):
        return self.px[y][x] if 0 <= x < SIZE and 0 <= y < SIZE else 0

    def ellipse(self, cx, cy, rx, ry, c, only=None):
        for y in range(SIZE):
            for x in range(SIZE):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1:
                    if only is None or self.px[y][x] in only:
                        self.px[y][x] = c

    def triangle(self, pts, c):
        (x0, y0), (x1, y1), (x2, y2) = pts

        def side(ax, ay, bx, by, px, py):
            return (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        for y in range(SIZE):
            for x in range(SIZE):
                px, py = x + 0.5, y + 0.5
                a = side(x0, y0, x1, y1, px, py)
                b = side(x1, y1, x2, y2, px, py)
                d = side(x2, y2, x0, y0, px, py)
                if (a >= 0 and b >= 0 and d >= 0) or (a <= 0 and b <= 0 and d <= 0):
                    self.px[y][x] = c

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, c)

    def points(self, pts, c):
        for x, y in pts:
            self.set(x, y, c)

    def outline(self):
        """Pixel-art outline: every empty pixel touching the shape turns dark."""
        edge = []
        for y in range(SIZE):
            for x in range(SIZE):
                if self.px[y][x] == 0 and any(self.get(x + dx, y + dy) not in (0, O)
                                              for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    edge.append((x, y))
        for x, y in edge:
            self.px[y][x] = O

    def rows(self):
        return ["".join("%x" % c for c in row) for row in self.px]


# ---------- the cat ----------

def body(c, tail=0, dy=0, puff=False, arm=None):
    """Fur, patches and outline. `tail` 0/1 sways the tail; `dy` lowers the head;
    `arm` raises the left paw to that height (waving)."""
    hy = 12 + dy
    # tail first, so the body covers its root
    tips = [((25, 27), (28, 24), (28, 19), (26, 16)), ((25, 27), (29, 25), (30, 21), (29, 17))][tail]
    for (ax, ay), (bx, by) in zip(tips, tips[1:]):
        for i in range(9):
            t = i / 8
            c.ellipse(ax + (bx - ax) * t + 0.5, ay + (by - ay) * t + 0.5, 1.6, 1.6, PATCH)
    c.ellipse(16, 24.5, 8.5 + (0.8 if puff else 0), 6.5, FUR)             # body
    c.ellipse(12, 29.5, 2.4, 1.6, FUR)                                     # front paws
    c.ellipse(20, 29.5, 2.4, 1.6, FUR)
    c.triangle([(5.5, hy - 2), (8, hy - 11), (14, hy - 6)], FUR)          # ears
    c.triangle([(26.5, hy - 2), (24, hy - 11), (18, hy - 6)], PATCH)
    c.ellipse(16, hy + 0.5, 11 + (0.6 if puff else 0), 8.5, FUR)        # head
    c.ellipse(22.5, hy - 3.5, 5, 4, PATCH, only=(FUR,))                    # patch over the right eye
    c.ellipse(22.5, 21.5, 3.2, 2.6, PATCH, only=(FUR,))                    # patch on the shoulder
    if arm is not None:                                                    # raised paw, outside the head
        for i in range(7):
            t = i / 6
            c.ellipse(8 + (3.5 - 8) * t, 22 + (arm + 2 - 22) * t, 1.7, 1.7, FUR)
        c.ellipse(3.5, arm, 2.4, 2.4, FUR)
    c.ellipse(16, 27, 6, 3, SHADE, only=(FUR,))                            # belly shade
    c.outline()
    c.triangle([(8, hy - 4), (9, hy - 9), (12.5, hy - 5.5)], PINK)          # inner ears
    c.triangle([(24, hy - 4), (23, hy - 9), (19.5, hy - 5.5)], PINK)
    for x in (12, 20):                                                     # toe lines
        c.set(x, 30, O)
    c.set(15, 29, O)


def face(c, eyes="open", mouth="w", dy=0, look=(0, 0), blush=True):
    hy = 12 + dy
    ey = hy + 1
    lx, rx = 10, 20
    ox, oy = look
    if eyes == "open":
        for x in (lx, rx):
            c.rect(x + ox, ey - 1 + oy, 2, 3, EYE)
            c.set(x + ox, ey - 1 + oy, HI)
    elif eyes == "big":
        for x in (lx, rx):
            c.rect(x - 1, ey - 2, 3, 4, EYE)
            c.set(x - 1, ey - 2, HI)
            c.set(x + 1, ey + 1, HI)
    elif eyes == "happy":                                     # ^ ^
        for x in (lx, rx):
            c.points([(x - 1, ey + 1), (x, ey), (x + 1, ey), (x + 2, ey + 1)], EYE)
    elif eyes == "closed":                                    # - -
        for x in (lx, rx):
            c.points([(x - 1, ey + 1), (x, ey + 1), (x + 1, ey + 1), (x + 2, ey + 1)], EYE)
    elif eyes == "x":
        for x in (lx, rx):
            c.points([(x - 1, ey - 1), (x + 2, ey - 1), (x, ey), (x + 1, ey), (x, ey + 1), (x + 1, ey + 1),
                      (x - 1, ey + 2), (x + 2, ey + 2)], EYE)
    elif eyes == "sad":                                       # open, brows sloping down outward
        for x in (lx, rx):
            c.rect(x, ey, 2, 2, EYE)
            c.set(x, ey, HI)
        c.points([(lx - 1, ey - 1), (lx, ey - 2), (lx + 1, ey - 2)], EYE)
        c.points([(rx + 2, ey - 1), (rx + 1, ey - 2), (rx, ey - 2)], EYE)
    elif eyes == "focus":                                     # looking down at the screen
        for x in (lx, rx):
            c.rect(x, ey + 1, 2, 2, EYE)
            c.points([(x - 1, ey), (x + 2, ey)], O)
    c.rect(15, hy + 3, 2, 1, PINK)                            # nose
    if mouth == "w":
        c.points([(14, hy + 4), (15, hy + 5), (16, hy + 5), (17, hy + 4)], O)
    elif mouth == "o":
        c.rect(15, hy + 4, 2, 2, O)
        c.set(15, hy + 5, 9)
    elif mouth == "smile":
        c.points([(13, hy + 4), (14, hy + 5), (15, hy + 5), (16, hy + 5), (17, hy + 5), (18, hy + 4)], O)
        c.rect(15, hy + 6, 2, 1, 9)
    elif mouth == "flat":
        c.points([(14, hy + 5), (15, hy + 5), (16, hy + 5), (17, hy + 5)], O)
    elif mouth == "wobble":
        c.points([(13, hy + 5), (14, hy + 4), (15, hy + 5), (16, hy + 4), (17, hy + 5), (18, hy + 4)], O)
    if blush:
        c.rect(7, hy + 3, 2, 1, PINK)
        c.rect(23, hy + 3, 2, 1, PINK)


def laptop(c, paws):
    """Laptop lid in front of the cat, paws tapping on top; `paws` 0/1 says which one is up."""
    c.rect(8, 24, 16, 7, LAPTOP)
    c.rect(8, 30, 16, 1, LAPTOP2)
    for x in range(7, 25):
        c.set(x, 23, O)
    for y in range(23, 31):
        c.set(7, y, O)
        c.set(24, y, O)
    c.rect(15, 26, 2, 2, GLOW)                                # logo
    for i, x in enumerate((10, 19)):
        top = 20 if i == paws else 21
        c.rect(x, top + 1, 3, 23 - top - 1, FUR)
        c.points([(x, top), (x + 1, top), (x + 2, top)], O)
        for y in range(top + 1, 23):
            c.points([(x - 1, y), (x + 3, y)], O)


def book(c, page):
    """An open book held up in front; `page` 0/1 flips a page corner."""
    c.rect(7, 21, 18, 8, BOOK)
    c.rect(8, 21, 7, 7, PAGE)
    c.rect(17, 21, 7, 7, PAGE)
    c.rect(15, 21, 2, 8, BOOK2)
    for y in (23, 25):
        c.rect(9, y, 5, 1, 3)
        c.rect(18, y, 5, 1, 3)
    if page:
        c.points([(22, 21), (23, 21), (23, 22)], 3)
    for x in range(6, 26):
        c.set(x, 20, O)
        c.set(x, 29, O)
    for y in range(20, 30):
        c.set(6, y, O)
        c.set(25, y, O)
    for x in (8, 21):                                         # paws on the cover
        c.rect(x, 26, 3, 2, FUR)
        c.points([(x - 1, 26), (x - 1, 27), (x + 3, 26), (x + 3, 27), (x, 28), (x + 1, 28), (x + 2, 28)], O)


def wave_pad(c, y):
    """Pink pad on the raised paw."""
    c.rect(3, y, 2, 1, PINK)


def frame(fn):
    c = Canvas()
    fn(c)
    return c.rows()


# name -> pose. Two frames per state; the UI alternates them.
FRAMES = {
    "idle_0":     lambda c: (body(c, 0), face(c)),
    "idle_1":     lambda c: (body(c, 1), face(c)),
    "blink":      lambda c: (body(c, 0), face(c, "closed")),
    "think_0":    lambda c: (body(c, 0), face(c, look=(1, -1), mouth="flat")),
    "think_1":    lambda c: (body(c, 1), face(c, look=(0, -1), mouth="flat")),
    "read_0":     lambda c: (body(c, 0), face(c, look=(-1, 1)), book(c, 0)),
    "read_1":     lambda c: (body(c, 0), face(c, look=(1, 1)), book(c, 1)),
    "type_0":     lambda c: (body(c, 0), face(c, "focus"), laptop(c, 0)),
    "type_1":     lambda c: (body(c, 0), face(c, "focus"), laptop(c, 1)),
    "wait_0":     lambda c: (body(c, 0, arm=18), face(c, "big", "o"), wave_pad(c, 18)),
    "wait_1":     lambda c: (body(c, 1, arm=15), face(c, "big", "o"), wave_pad(c, 15)),
    "done_0":     lambda c: (body(c, 0), face(c, "happy", "smile")),
    "done_1":     lambda c: (body(c, 1), face(c, "happy", "smile")),
    "error_0":    lambda c: (body(c, 0, puff=True), face(c, "x", "wobble", blush=False)),
    "error_1":    lambda c: (body(c, 1, puff=True), face(c, "x", "wobble", blush=False)),
    "sleep_0":    lambda c: (body(c, 0, dy=1), face(c, "closed", "flat", dy=1)),
    "sleep_1":    lambda c: (body(c, 0, dy=2), face(c, "closed", "flat", dy=2)),
    "hungry_0":   lambda c: (body(c, 0, dy=1), face(c, "sad", "flat", dy=1)),
    "hungry_1":   lambda c: (body(c, 1, dy=1), face(c, "sad", "flat", dy=1)),
}


def build():
    return {name: frame(fn) for name, fn in FRAMES.items()}


def rgb565(c):
    return ((c >> 8) & 0xF800) | ((c >> 5) & 0x07E0) | ((c >> 3) & 0x001F)


def write_header(frames, path):
    names = list(frames)
    lines = ["// Generated by tools/cat_art.py -- do not edit; change the script and rerun it.",
             "// An original 32x32 pixel cat (the \"cat\" skin). Rows are hex palette indices, 0 = transparent.",
             "#pragma once", "", "#include <stdint.h>", "", "namespace pet {", "",
             "constexpr int kCatSize = %d;" % SIZE, "",
             "const uint16_t kCatPalette[16] = {"]
    lines.append("    " + ", ".join("0x%04X" % (rgb565(c) if c is not None else 0) for c in PALETTE) + ",")
    lines += ["};", "", "enum CatFrame : uint8_t {"]
    lines += ["  kCat_%s," % n for n in names]
    lines += ["  kCatFrameCount", "};", "", "const char kCatFrames[kCatFrameCount][kCatSize][kCatSize + 1] = {"]
    for n in names:
        lines.append("    {  // %s" % n)
        lines += ['        "%s",' % row for row in frames[n]]
        lines.append("    },")
    lines += ["};", "", "}  // namespace pet", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_js(frames, path):
    data = {"size": SIZE, "palette": ["#%06x" % c if c is not None else None for c in PALETTE], "frames": frames}
    with open(path, "w") as f:
        f.write("// Generated by firmware/tools/cat_art.py -- do not edit; change the script and rerun it.\n")
        f.write("// An original 32x32 pixel cat (the \"cat\" skin), the same pixels the device draws.\n")
        f.write("window.CAT_ART = %s;\n" % json.dumps(data, separators=(",", ":")))


def write_pngs(frames, out, scale=8):
    from PIL import Image
    os.makedirs(out, exist_ok=True)
    names = list(frames)
    sheet = Image.new("RGB", (len(names) * (SIZE * scale + 8) + 8, SIZE * scale + 16), (11, 13, 16))
    for i, n in enumerate(names):
        img = Image.new("RGB", (SIZE, SIZE), (11, 13, 16))
        for y, row in enumerate(frames[n]):
            for x, ch in enumerate(row):
                c = PALETTE[int(ch, 16)]
                if c is not None:
                    img.putpixel((x, y), (c >> 16, (c >> 8) & 255, c & 255))
        big = img.resize((SIZE * scale, SIZE * scale), Image.NEAREST)
        big.save(os.path.join(out, "cat-%s.png" % n))
        sheet.paste(big, (8 + i * (SIZE * scale + 8), 8))
    sheet.save(os.path.join(out, "cat-sheet.png"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--png", help="also write enlarged PNGs here")
    args = p.parse_args(argv)
    frames = build()
    write_header(frames, os.path.join(FIRMWARE, "src", "cat_art.h"))
    write_js(frames, os.path.join(ROOT, "web", "cat_art.js"))
    if args.png:
        write_pngs(frames, args.png)
    print("wrote %d frames" % len(frames))
    return 0


if __name__ == "__main__":
    sys.exit(main())
