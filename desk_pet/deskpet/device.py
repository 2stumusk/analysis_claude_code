"""USB serial link to the deskpet firmware (desk_pet/firmware).

The daemon sends one compact JSON frame per line (format in
firmware/src/frame.h) whenever the screen would change, and at least every
HEARTBEAT seconds so the device keeps its clock and knows the link is alive.
The device sends {"hello": "deskpet", ...} until it hears from us, and
{"btn": "B", "agent": <id on screen>} when button B is pressed, with
"all": 1 for a long press.

pyserial is used when installed; otherwise POSIX termios (macOS / Linux).
"""

import glob
import json
import os
import select
import sys
import threading
import time

BAUD = 115200
HEARTBEAT = 5.0
MAX_AGENTS = 8
HELLO_WAIT = 4.0
# USB-serial bridges found on ESP32 boards: CH340/CH9102, CP210x, FTDI, Espressif native.
KNOWN_VIDS = {0x1A86, 0x10C4, 0x0403, 0x303A}
POSIX_PATTERNS = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*",
                  "/dev/cu.SLAB_USBtoUART*", "/dev/cu.usbmodem*"]


def ascii_clip(text, limit):
    """Printable ASCII only (the device fonts have nothing else), at most `limit` chars."""
    out = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text or ""))
    return out if len(out) <= limit else out[: limit - 3] + "..."


def tz_offset(now):
    return int(time.localtime(now).tm_gmtoff or 0)


def device_frame(snap, now=None):
    """Turn an App.snapshot() into the frame the firmware parses."""
    now = time.time() if now is None else now
    order = list(snap.get("order") or snap["agents"])[:MAX_AGENTS]
    agents = []
    for name in order:
        a = snap["agents"][name]
        busy = a["state"] not in ("idle", "offline")
        agents.append({
            "id": ascii_clip(name, 11),
            "l": ascii_clip(a.get("label") or name.upper(), 9),
            "b": ascii_clip(a.get("abbr") or name[:2].upper(), 3),
            "s": a["state"],
            "d": ascii_clip(a.get("detail"), 48),
            "c": ascii_clip(a.get("cwd"), 22),
            "e": max(0, int(now - a["task_start"])) if busy and a.get("task_start") else -1,
            "n": int(a.get("tools") or 0),
            "k": int(a.get("sessions") or 0),
            "x": 1 if a.get("alert") else 0,
        })
    p = snap["pet"]

    def age(ts):
        return round(now - ts, 1) if ts else -1

    usage = (snap.get("usage") or {}).get("claude")
    return {
        "v": 1,
        "t": int(now),
        "tz": tz_offset(now),
        "f": order.index(snap["focus"]) if snap.get("focus") in order else -1,
        "a": agents,
        "p": {"lv": p["level"], "xi": p["xp"] - p["xp_level"], "xs": p["xp_next"] - p["xp_level"],
              "en": p["energy"], "md": p["mood"], "tk": p["tasks_today"], "tl": p["tools_today"],
              "er": p["errors_today"], "lu": age(p.get("levelup_at")), "fd": age(p.get("fed_at"))},
        "u": ({"o": usage["output"], "t": usage["input"] + usage["output"] + usage["cache_write"]}
              if usage else None),
        "pg": "".join(PAGE_LETTERS[p] for p in snap.get("pages") or PAGE_LETTERS if p in PAGE_LETTERS),
        "ro": ([snap["rotation"]["index"], snap["rotation"]["count"]]
               if snap.get("rotation") and snap.get("focus") in order else None),
        "w": weather_frame(snap.get("weather")),
    }


PAGE_LETTERS = {"face": "f", "clock": "c", "weather": "w", "agents": "a", "stats": "s"}


def weather_frame(w):
    """The weather part of a frame: None when no city is set."""
    if not w:
        return None
    if w.get("status") not in ("ok", "stale"):
        return {"st": w.get("status", "loading"), "c": ascii_clip(w.get("query"), 15)}
    return {
        "st": w["status"],
        "c": ascii_clip(w["city"], 15),
        "tx": ascii_clip(w["text"], 20),
        "k": w["kind"],
        "dy": 1 if w.get("day", True) else 0,
        "t": w["temp"], "fl": w["feels"], "hu": w["humidity"], "ws": w["wind"],
        "hi": w["hi"] if w["hi"] is not None else -99, "lo": w["lo"] if w["lo"] is not None else -99,
        "p": w["pop"], "ag": w["age"] // 60,
        "sm": 1 if w.get("sample") else 0,
        "h": [[h["h"], h["t"], h["k"], h["p"], h["d"]] for h in w["hours"]],
    }


def frame_key(snap, frame):
    """What has to change for a frame to be worth sending before the heartbeat.

    Ticking values (time, task timers, ages) are left out; the device advances
    them itself."""
    agents = [dict(a, e=a["e"] >= 0) for a in frame["a"]]
    pet = dict(frame["p"], lu=snap["pet"].get("levelup_at"), fd=snap["pet"].get("fed_at"))
    weather = dict(frame["w"], ag=None) if frame["w"] else None
    return json.dumps([frame["f"], agents, pet, frame["u"], frame["pg"], weather, frame["ro"]], sort_keys=True)


def encode(frame):
    return (json.dumps(frame, separators=(",", ":")) + "\n").encode("ascii")


# ---------- serial ports ----------

class PosixPort:
    """Raw 8N1 serial port through termios; no third-party packages."""

    def __init__(self, path, baud=BAUD):
        import termios
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            attrs = termios.tcgetattr(self.fd)
            speed = getattr(termios, "B%d" % baud)
            attrs[0] = 0                                          # iflag
            attrs[1] = 0                                          # oflag
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # no HUPCL: keep DTR on close
            attrs[3] = 0                                          # lflag: raw
            attrs[4] = attrs[5] = speed
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except Exception:
            os.close(self.fd)
            raise

    def read(self, timeout):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return b""
        data = os.read(self.fd, 4096)
        if not data:
            raise OSError("serial port closed")
        return data

    def write(self, data):
        view = memoryview(data)
        while view:
            select.select([], [self.fd], [], 1.0)
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                continue
            view = view[n:]

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class PySerialPort:
    def __init__(self, path, baud=BAUD):
        import serial
        self.path = path
        self.s = serial.Serial()
        self.s.port = path
        self.s.baudrate = baud
        self.s.timeout = 0
        self.s.dtr = False  # keep ESP32 auto-reset circuits released
        self.s.rts = False
        self.s.open()

    def read(self, timeout):
        self.s.timeout = timeout
        first = self.s.read(1)
        return first + (self.s.read(self.s.in_waiting) if first and self.s.in_waiting else b"")

    def write(self, data):
        self.s.write(data)

    def close(self):
        try:
            self.s.close()
        except Exception:  # noqa: BLE001
            pass


def has_pyserial():
    try:
        import serial  # noqa: F401
        import serial.tools.list_ports  # noqa: F401
    except ImportError:
        return False
    return True


def open_port(path):
    if has_pyserial():
        return PySerialPort(path)
    if os.name == "nt":
        raise RuntimeError("Windows needs pyserial: pip install pyserial")
    return PosixPort(path)


def candidate_ports():
    if has_pyserial():
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        known = [p.device for p in ports if p.vid in KNOWN_VIDS]
        return known or [p.device for p in ports]
    found = []
    for pattern in POSIX_PATTERNS:
        found += sorted(glob.glob(pattern))
    return found


def read_lines(buf, data):
    """Append `data` to `buf`; return (complete lines, rest)."""
    buf += data
    *lines, rest = buf.split(b"\n")
    return [ln.strip() for ln in lines if ln.strip()], rest[-8192:]


def parse_line(raw):
    try:
        msg = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None  # boot ROM chatter and the like
    return msg if isinstance(msg, dict) else None


def wait_for_hello(port, timeout=HELLO_WAIT):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        lines, buf = read_lines(buf, port.read(0.2))
        for raw in lines:
            msg = parse_line(raw)
            if msg and msg.get("hello") == "deskpet":
                return msg
    return None


class SerialLink:
    """Keeps a device in sync with an App, reconnecting as needed."""

    def __init__(self, app, port="auto", log=None):
        self.app = app
        self.want = port
        self.log = log or (lambda msg: print("deskpet: " + msg, file=sys.stderr))
        self.stop = threading.Event()

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self

    def connect(self):
        paths = candidate_ports() if self.want == "auto" else [self.want]
        for path in paths:
            try:
                port = open_port(path)
            except Exception as e:  # noqa: BLE001 - busy or vanished ports are expected
                if self.want != "auto":
                    self.log("cannot open %s: %s" % (path, e))
                continue
            hello = wait_for_hello(port)
            if hello or self.want != "auto":
                return port, hello or {}
            port.close()
        return None, None

    def run(self):
        announced_missing = False
        while not self.stop.is_set():
            try:
                port, hello = self.connect()
            except RuntimeError as e:
                self.log(str(e))
                return
            if not port:
                if not announced_missing:
                    self.log("no deskpet device found on USB yet; still looking")
                    announced_missing = True
                self.stop.wait(3)
                continue
            announced_missing = False
            self.app.set_device({"port": port.path, "board": hello.get("board"), "fw": hello.get("fw")})
            self.log("device on %s (%s)" % (port.path, hello.get("board") or "unknown board"))
            try:
                self.session(port)
            except OSError as e:
                self.log("device link lost: %s" % e)
            finally:
                port.close()
                self.app.set_device(None)
            self.stop.wait(1)

    def session(self, port):
        last_key, last_sent, buf = None, 0.0, b""
        while not self.stop.is_set():
            snap = self.app.snapshot()
            frame = device_frame(snap)
            key = frame_key(snap, frame)
            if key != last_key or time.time() - last_sent >= HEARTBEAT:
                port.write(encode(frame))
                last_key, last_sent = key, time.time()
            lines, buf = read_lines(buf, port.read(0.15))
            for raw in lines:
                msg = parse_line(raw)
                if not msg:
                    continue
                if msg.get("btn") == "B":
                    agent = msg.get("agent") if isinstance(msg.get("agent"), str) else None
                    self.app.button("B", agent, bool(msg.get("all")))
                elif msg.get("hello") == "deskpet":
                    last_key = None  # the device restarted: resend now
