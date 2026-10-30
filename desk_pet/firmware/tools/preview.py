#!/usr/bin/env python3
"""Render the firmware's screens on the desktop, without a board.

Builds tools/preview_main.cpp together with the firmware's own UI and frame
parser (src/ui.cpp, src/frame.cpp, src/model.cpp), feeds it frames made by the
deskpet daemon's device link (deskpet/device.py), and draws the recorded calls
with Pillow. Text is drawn from LovyanGFX's font tables, read as data, so glyph
shapes and widths match the device.

  python3 tools/preview.py --lgfx ~/src/LovyanGFX --out preview/

Needs a C++17 compiler and Pillow.
"""

import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(FIRMWARE))  # desk_pet/, for the deskpet package

from deskpet.device import device_frame  # noqa: E402
from deskpet.server import App  # noqa: E402

# Same order as enum class Font in src/gfx.h.
FONTS = [
    ("Custom/DejaVu9.h", "DejaVu9"),
    ("Custom/DejaVu12.h", "DejaVu12"),
    ("Custom/DejaVu18.h", "DejaVu18"),
    ("GFXFF/FreeSansBold9pt7b.h", "FreeSansBold9pt7b"),
    ("GFXFF/FreeSansBold12pt7b.h", "FreeSansBold12pt7b"),
    ("GFXFF/FreeMono9pt7b.h", "FreeMono9pt7b"),
    ("GFXFF/FreeMonoBold9pt7b.h", "FreeMonoBold9pt7b"),
    ("Custom/DejaVu24.h", "DejaVu24"),
    ("Custom/DejaVu72.h", "DejaVu72"),
]
VIEWS = {"face": 0, "clock": 1, "weather": 2, "agents": 3, "stats": 4}


# ---------- fonts ----------

class GfxFont:
    """An Adafruit-GFX font table: 1-bit glyph bitmaps plus per-glyph metrics."""

    def __init__(self, path, name):
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        bitmaps = re.search(r"%sBitmaps\[\]\s*PROGMEM\s*=\s*\{(.*?)\};" % name, src, re.S)
        glyphs = re.search(r"%sGlyphs\[\]\s*PROGMEM\s*=\s*\{(.*?)\};" % name, src, re.S)
        if not bitmaps or not glyphs:
            raise ValueError("no font tables named %s in %s" % (name, path))
        self.bits = bytes(int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", bitmaps.group(1)))
        rows = re.findall(r"\{\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\s*\}",
                          re.sub(r"//[^\n]*", "", glyphs.group(1)))
        self.glyphs = [tuple(int(v) for v in r) for r in rows]  # offset, w, h, adv, xo, yo
        if len(self.glyphs) != 95:
            raise ValueError("%s: expected 95 glyphs, found %d" % (name, len(self.glyphs)))

    def advance(self, ch):
        return self.glyphs[ord(ch) - 32][3] if 32 <= ord(ch) < 127 else 0

    def width(self, text):
        return sum(self.advance(ch) for ch in text)

    def draw(self, px, text, x, baseline, color, size):
        cx = x
        for ch in text:
            if not 32 <= ord(ch) < 127:
                continue
            off, w, h, adv, xo, yo = self.glyphs[ord(ch) - 32]
            bit = 0
            for yy in range(h):
                for xx in range(w):
                    byte = self.bits[off + (bit >> 3)]
                    if byte & (0x80 >> (bit & 7)):
                        X, Y = cx + xo + xx, baseline + yo + yy
                        if 0 <= X < size[0] and 0 <= Y < size[1]:
                            px[X, Y] = color
                    bit += 1
            cx += adv


def load_fonts(lgfx_root):
    base = os.path.join(lgfx_root, "src", "lgfx", "Fonts")
    return [GfxFont(os.path.join(base, rel), name) for rel, name in FONTS]


# ---------- harness ----------

def build_harness(out_dir, cxx):
    exe = os.path.join(out_dir, "preview_main")
    srcs = [os.path.join(HERE, "preview_main.cpp")] + [
        os.path.join(FIRMWARE, "src", n) for n in ("ui.cpp", "frame.cpp", "model.cpp")]
    subprocess.run([cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-o", exe, *srcs], check=True)
    return exe


def rgb565(c):
    c = int(c)
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def paint(commands, fonts):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (320, 240), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    px = img.load()
    for cmd in commands:
        if cmd.startswith("S "):
            head, text = cmd[2:].split("|", 1)
            x, y, f, align, c = (int(v) for v in head.split())
            font = fonts[f]
            w = font.width(text)
            x = x if align == 0 else (x - w // 2 if align == 1 else x - w)
            font.draw(px, text, x, y, rgb565(c), img.size)
            continue
        op, *args = cmd.split()
        v = [float(a) for a in args]
        col = rgb565(v[-1])
        if op == "R":
            x, y, w, h = v[:4]
            if w > 0 and h > 0:
                draw.rectangle([x, y, x + w - 1, y + h - 1], fill=col)
        elif op in ("RR", "DR"):
            x, y, w, h, r = v[:5]
            if w > 0 and h > 0:
                r = max(0, min(r, (w - 1) / 2, (h - 1) / 2))
                box = [x, y, x + w - 1, y + h - 1]
                if op == "RR":
                    draw.rounded_rectangle(box, radius=r, fill=col)
                else:
                    draw.rounded_rectangle(box, radius=r, outline=col, width=1)
        elif op == "C":
            x, y, r = v[:3]
            draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        elif op == "T":
            draw.polygon([(v[0], v[1]), (v[2], v[3]), (v[4], v[5])], fill=col)
        elif op == "A":
            x, y, r0, r1, a0, a1 = v[:6]
            draw.arc([x - r1, y - r1, x + r1, y + r1], a0, a1, fill=col, width=int(r1 - r0 + 1))
        elif op == "L":
            x0, y0, x1, y1, r = v[:5]
            draw.line([x0, y0, x1, y1], fill=col, width=max(1, round(2 * r)))
            for x, y in ((x0, y0), (x1, y1)):
                draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
    return img


# ---------- scenes ----------

def ev(name, sid, **kw):
    return dict(hook_event_name=name, session_id=sid, **kw)


def tool(name, sid, **inp):
    return ev("PreToolUse", sid, tool_name=name, tool_input=inp)


def sample_weather(kind="rain", code=61, day=True, temp=17):
    """Made-up numbers for screenshots; the screen labels them "sample data"."""
    sky = ["partly", "rain", "rain", "cloudy", "cloudy", "clear"]
    from deskpet.weather import describe
    return {"status": "ok", "sample": True, "city": "Wuxi", "query": "无锡", "temp": temp, "feels": temp - 1,
            "humidity": 82, "wind": 14, "code": code, "kind": kind, "day": day, "text": describe(code)[1],
            "text_zh": describe(code)[2], "hi": temp + 4, "lo": temp - 3, "pop": 70, "age": 300,
            "updated": 0, "source": "sample",
            "hours": [{"h": (15 + 2 * i) % 24, "t": temp + 2 - i, "k": sky[i], "p": 40, "d": 1 if i < 2 else 0}
                      for i in range(6)]}


def scene(agents, events, later=125, tweak=None, weather=None, pages=None):
    """Frame for an App that saw `events`, `later` seconds after they happened."""
    app = App(usage=False, weather_factory=None)
    app.set_config({"agents": agents, "pages": pages or ["face", "clock", "weather", "agents", "stats"]})
    for agent, payload in events:
        app.handle_hook(agent, payload)
    if tweak:
        tweak(app)
    snap = app.snapshot()
    if tweak and hasattr(tweak, "usage"):
        snap["usage"] = tweak.usage
    if weather is not None:
        snap["weather"] = weather
    return device_frame(snap, now=time.time() + later)


def held(agent, tool_name, tool_input, wait=30):
    """A tweak that leaves a permission request held for the device's buttons."""
    def tweak(app):
        from deskpet.approvals import describe_request
        app.config["approvals"] = True
        app.approvals.open(agent, "c", tool_name, describe_request(tool_name, tool_input), wait)
    return tweak


def scenes():
    duo = ["claude", "codex"]
    start = [("claude", ev("SessionStart", "c", cwd="/work/shop-api")),
             ("codex", ev("SessionStart", "x", cwd="/work/pet-firmware")),
             ("claude", ev("UserPromptSubmit", "c")), ("codex", ev("UserPromptSubmit", "x"))]
    eight = ["claude", "codex", "gemini", "qwen", "kimi", "deepseek", "grok", "muse"]
    busy8 = [(a, ev("UserPromptSubmit", a)) for a in eight] + [
        ("claude", tool("Read", "claude", file_path="/w/src/cart.ts")),
        ("codex", tool("Bash", "codex", command="cargo build --release")),
        ("gemini", ev("AfterAgent", "gemini")),
        ("kimi", tool("Shell", "kimi", command="npm run build")),
        ("deepseek", tool("Edit", "deepseek", file_path="/w/guide.md", old_string="a")),
        ("grok", ev("Notification", "grok", notification_type="permission_prompt",
                    message="Grok wants to run rm -rf build")),
        ("muse", ev("StopFailure", "muse", error="tests failed")),
    ]

    def hungry(app):
        app.pet.data["energy"] = 12

    def with_usage(app):
        app.pet.data.update(xp=230, tasks_today=9, tools_today=128, errors_today=1)
    with_usage.usage = {"claude": {"date": "", "input": 41200, "output": 123400, "cache_read": 9e6,
                                   "cache_write": 187000, "messages": 79}}

    yield "face-offline-nolink", "face", "-", None
    yield "face-idle-offline", "face", "-", scene(duo, [])
    yield "face-thinking", "face", "-", scene(duo, start)
    yield "face-reading", "face", "-", scene(duo, start + [("claude", tool("Read", "c", file_path="/work/shop-api/src/cart.ts"))])
    yield "face-editing", "face", "-", scene(duo, start + [("claude", tool("Edit", "c", file_path="/work/shop-api/src/cart.ts", old_string="a"))])
    yield "face-running", "face", "-", scene(duo, start + [("claude", tool("Bash", "c", command="npm test -- cart --coverage --reporter=dot"))])
    yield "face-waiting", "face", "-", scene(duo, start + [("claude", ev("Notification", "c", notification_type="permission_prompt", message="Claude needs your permission to use Bash"))])
    yield "face-done", "face", "-", scene(["claude"], start[:1] + [("claude", ev("UserPromptSubmit", "c")), ("claude", ev("Stop", "c"))], later=3)
    yield "face-error", "face", "-", scene(["codex"], start[1:2] + [("codex", ev("UserPromptSubmit", "x")), ("codex", ev("StopFailure", "x", error="cargo test: 2 failed"))], later=3)
    yield "face-hungry", "face", "-", scene(duo, start[:2], tweak=hungry)
    yield "face-8-agents", "face", "-", scene(eight, busy8)
    three = ["claude", "codex", "kimi"]
    busy3 = [(a, ev("UserPromptSubmit", a)) for a in three] + [
        ("codex", tool("Bash", "codex", command="cargo build --release"))]
    yield "face-rotating", "face", "-", scene(three, busy3)
    yield "agents-focus-marker", "agents", "-", scene(three, busy3)
    yield "clock-2", "clock", "-", scene(duo, start + [("codex", tool("Bash", "x", command="cargo test"))])
    yield "clock-8", "clock", "-", scene(eight, busy8)
    yield "agents-2", "agents", "-", scene(duo, start + [("claude", ev("Notification", "c", notification_type="permission_prompt")), ("codex", tool("Bash", "x", command="cargo build --release"))])
    yield "agents-3", "agents", "-", scene(["kimi", "deepseek", "qwen"], [("kimi", ev("UserPromptSubmit", "k")), ("kimi", tool("Read", "k", file_path="/w/README.md")), ("deepseek", ev("SessionStart", "d", cwd="/w/docs-site")), ("qwen", ev("UserPromptSubmit", "q")), ("qwen", tool("Edit", "q", file_path="/w/guide.md", old_string="a"))])
    yield "agents-8", "agents", "-", scene(eight, busy8)
    yield "stats", "stats", "-", scene(duo, start[:2], tweak=with_usage)
    yield "weather-rain", "weather", "-", scene(duo, start, weather=sample_weather())
    yield "weather-clear-night", "weather", "-", scene(duo, start, weather=sample_weather("clear", 0, False, 11))
    yield "weather-thunder", "weather", "-", scene(duo, start, weather=sample_weather("thunder", 95, True, 29))
    yield "weather-snow", "weather", "-", scene(duo, start, weather=sample_weather("snow", 73, True, -2))
    yield "weather-off", "weather", "-", scene(duo, start)
    yield "clock-weather", "clock", "-", scene(duo, start, weather=sample_weather())
    yield "clock-3-pages", "clock", "-", scene(duo, start, weather=sample_weather(), pages=["face", "clock", "weather"])
    cmd = {"command": "git push --force-with-lease origin feature/cart-discounts && npm run deploy:staging"}
    yield "approval-bash", "face", "-", scene(duo, start, later=8, tweak=held("claude", "Bash", cmd))
    yield "approval-codex-edit", "agents", "-", scene(duo, start, later=26, tweak=held(
        "codex", "apply_patch", {"path": "/work/shop-api/src/cart/discounts.rs"}))
    yield "approval-touch", "face", "halves", scene(duo, start, later=8, tweak=held("claude", "Bash", cmd))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--lgfx", required=True, help="LovyanGFX checkout (for its font tables)")
    p.add_argument("--out", default="preview")
    p.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    p.add_argument("--scale", type=int, default=2)
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    fonts = load_fonts(args.lgfx)
    metrics = os.path.join(args.out, "metrics.txt")
    with open(metrics, "w") as f:
        for i, font in enumerate(fonts):
            f.write("%d %s\n" % (i, " ".join(str(g[3]) for g in font.glyphs)))
    exe = build_harness(args.out, args.cxx)

    import json
    names, lines = [], []
    for name, view, preview, frame in scenes():
        names.append(name)
        lines.append("\t".join([name, str(VIEWS[view]), preview, "1000",
                                json.dumps(frame, separators=(",", ":")) if frame else "-"]))
    out = subprocess.run([exe, "render", metrics], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, check=True).stdout

    images, current, cmds = {}, None, []
    for line in out.splitlines():
        if line.startswith("BEGIN "):
            current, cmds = line[6:], []
        elif line == "END":
            images[current] = paint(cmds, fonts)
        else:
            cmds.append(line)

    from PIL import Image
    s = args.scale
    for name in names:
        images[name].resize((320 * s, 240 * s), Image.NEAREST).save(os.path.join(args.out, name + ".png"))
    cols = 3
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (320 + 8) + 8, rows * (240 + 8) + 8), (40, 40, 40))
    for i, name in enumerate(names):
        sheet.paste(images[name], (8 + (i % cols) * 328, 8 + (i // cols) * 248))
    sheet.save(os.path.join(args.out, "sheet.png"))
    print("wrote %d screens to %s" % (len(names), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
