import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deskpet import device  # noqa: E402
from deskpet.device import SerialLink, ascii_clip, device_frame, encode, frame_key  # noqa: E402
from deskpet.server import App  # noqa: E402

FIRMWARE = os.path.join(ROOT, "firmware")


def ev(name, sid="s1", **kw):
    return dict(hook_event_name=name, session_id=sid, **kw)


def busy_app(agents=("claude", "codex")):
    app = App(usage=False)
    app.set_config({"agents": list(agents)})
    app.handle_hook("claude", ev("SessionStart", "c", cwd="/work/购物车-api"))
    app.handle_hook("claude", ev("UserPromptSubmit", "c"))
    app.handle_hook("claude", ev("PreToolUse", "c", tool_name="Bash",
                                 tool_input={"command": "pytest 测试 -k 'x' " + "-v " * 40}))
    app.handle_hook("codex", ev("Notification", "x", notification_type="permission_prompt"))
    return app


class FrameTest(unittest.TestCase):
    def test_ascii_clip(self):
        self.assertEqual(ascii_clip("héllo 世界", 20), "h?llo ??")
        self.assertEqual(ascii_clip("x" * 30, 10), "xxxxxxx...")
        self.assertEqual(ascii_clip(None, 5), "")

    def test_frame_shape(self):
        app = busy_app()
        snap = app.snapshot()
        now = time.time() + 65
        f = device_frame(snap, now=now)
        self.assertEqual((f["v"], f["t"], f["f"]), (1, int(now), 1))  # codex waits: focus
        claude, codex = f["a"]
        self.assertEqual((claude["id"], claude["l"], claude["b"], claude["s"]), ("claude", "CLAUDE", "CL", "running"))
        self.assertTrue(claude["d"].startswith("pytest ?? -k"))
        self.assertLessEqual(len(claude["d"]), 48)
        self.assertEqual(claude["c"], "???-api")
        self.assertGreaterEqual(claude["e"], 64)
        self.assertEqual((codex["s"], codex["x"], codex["e"]), ("waiting", 1, -1))
        self.assertTrue(all(ord(ch) < 128 for ch in encode(f).decode()))
        self.assertEqual(f["u"], None)

    def test_key_ignores_ticking_values(self):
        app = busy_app()
        snap = app.snapshot()
        a, b = device_frame(snap, now=time.time()), device_frame(snap, now=time.time() + 30)
        self.assertNotEqual(a, b)
        self.assertEqual(frame_key(snap, a), frame_key(snap, b))
        app.handle_hook("claude", ev("Stop", "c"))
        snap2 = app.snapshot()
        self.assertNotEqual(frame_key(snap2, device_frame(snap2)), frame_key(snap, a))

    def test_at_most_eight_agents(self):
        app = App(usage=False)
        app.set_config({"agents": ["claude", "codex", "gemini", "qwen", "kimi", "deepseek", "grok", "muse"]})
        f = device_frame(app.snapshot())
        self.assertEqual(len(f["a"]), 8)
        self.assertLess(len(encode(f)), 4096)  # the firmware's line buffer

    def test_read_lines(self):
        lines, rest = device.read_lines(b"", b'{"a":1}\r\n\x00garbage\n{"b"')
        self.assertEqual(lines, [b'{"a":1}', b"\x00garbage"])
        self.assertEqual(rest, b'{"b"')
        self.assertIsNone(device.parse_line(b"\x00garbage"))
        self.assertEqual(device.parse_line(b'{"btn":"B"}'), {"btn": "B"})


@unittest.skipUnless(shutil.which("g++") or shutil.which("c++"), "needs a C++ compiler")
class FirmwareParseTest(unittest.TestCase):
    """The daemon's frames, read back by the firmware's own parser."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.exe = os.path.join(cls.tmp.name, "preview_main")
        cxx = shutil.which("g++") or shutil.which("c++")
        srcs = [os.path.join(FIRMWARE, "tools", "preview_main.cpp")] + [
            os.path.join(FIRMWARE, "src", n) for n in ("ui.cpp", "frame.cpp", "model.cpp")]
        subprocess.run([cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-o", cls.exe, *srcs],
                       check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def parse(self, *lines):
        out = subprocess.run([self.exe, "parse"], input="\n".join(lines) + "\n",
                             capture_output=True, text=True, check=True).stdout
        return [json.loads(x) for x in out.splitlines()]

    def test_round_trip(self):
        app = busy_app()
        app.pet.data.update(xp=230, tasks_today=3, tools_today=17, errors_today=1, energy=12)
        snap = app.snapshot()
        snap["usage"] = {"claude": {"input": 5, "output": 1234, "cache_read": 9, "cache_write": 6}}
        # 2026-10-26 23:59:50 UTC, shown in UTC+8: the next day on the device.
        frame = device_frame(snap, now=1793059190)
        frame["tz"] = 8 * 3600
        (got,) = self.parse(encode(frame).decode().strip())
        self.assertTrue(got["ok"])
        self.assertEqual(got["focus"], 1)
        claude, codex = got["agents"]
        self.assertEqual(claude[:4], ["claude", "CLAUDE", "CL", "RUNNING"])
        self.assertEqual(claude[4], frame["a"][0]["d"])
        self.assertEqual(claude[5], "???-api")
        self.assertEqual(codex[3], "NEEDS YOU")
        self.assertEqual(codex[-1], 1)
        self.assertEqual(got["pet"], [2, 130, 200, 12, 0, 3, 17, 1])  # mood 0 = hungry
        self.assertEqual(got["usage"], 1234)
        self.assertEqual(got["time"], "2026-10-27 07:59:50 w2")  # Tuesday

    def test_approval_round_trip(self):
        app = busy_app()
        app.config["approvals"] = True
        app.approvals.open("codex", "x", "Bash", "git push --force " + "x" * 200, 45)
        frame = device_frame(app.snapshot(), now=1793059190)
        (got,) = self.parse(encode(frame).decode().strip())
        active, agent, deadline, wait, rid, label, tool, detail = got["approval"]
        self.assertEqual((active, agent, wait, label, tool), (1, 1, 45, "CODEX", "Bash"))
        self.assertEqual(rid, app.approvals.current().id)
        self.assertEqual(deadline, int(app.approvals.current().deadline))
        self.assertEqual(detail, frame["ap"]["d"])
        self.assertEqual(len(detail), 120)
        (none,) = self.parse('{"v":1,"a":[]}')
        self.assertEqual(none["approval"][0], 0)

    def test_rejects_bad_frames(self):
        results = self.parse('{"v":2,"a":[]}', '{"v":1}', '{"v":1,"a":[', "not json",
                             '{"v":1,"a":[{"id":"x","s":"weird"}],"f":7}')
        self.assertEqual([r["ok"] for r in results], [False, False, False, False, True])
        self.assertEqual(results[-1]["focus"], -1)
        self.assertEqual(results[-1]["agents"][0][3], "IDLE")  # unknown states fall back to idle

    def test_escapes_and_unicode(self):
        line = json.dumps({"v": 1, "f": 0, "a": [{"id": "claude", "l": "CLAUDE", "s": "running",
                                                  "d": 'say "hi"\\now é 世'}]}, ensure_ascii=False)
        (got,) = self.parse(line)
        self.assertEqual(got["agents"][0][4], 'say "hi"\\now ? ?')


@unittest.skipUnless(hasattr(os, "openpty") and os.name == "posix", "needs a POSIX pty")
class SerialLinkTest(unittest.TestCase):
    """A fake board on a pseudo-terminal, driven through the termios port."""

    def test_handshake_frames_and_button(self):
        import tty
        master, slave = os.openpty()
        tty.setraw(slave)  # no echo of what the "board" writes
        path = os.ttyname(slave)
        app = busy_app()
        pressed = []
        app.button = lambda *args: pressed.append(args) or "ack"
        app.decide = lambda *args: pressed.append(args) or True
        old = device.has_pyserial
        device.has_pyserial = lambda: False  # exercise the termios path
        link = SerialLink(app, path, log=lambda msg: None)
        try:
            link.start()
            # Like the firmware: boot chatter, then a hello every so often until spoken to.
            os.write(master, b"\x00boot noise\r\n")
            hello = b'{"hello":"deskpet","fw":"0.1.0","board":"fake"}\n'
            self.wait_for(lambda: os.write(master, hello) and app.device is not None, step=0.3)
            self.assertEqual(app.device, {"port": path, "board": "fake", "fw": "0.1.0"})
            frame = self.read_frame(master)
            self.assertEqual([a["id"] for a in frame["a"]], ["claude", "codex"])

            os.write(master, b'{"btn":"B","agent":"codex"}\n{"btn":"B","all":1}\n')
            self.wait_for(lambda: pressed == [("B", "codex", False), ("B", None, True)])
            os.write(master, b'{"approval":"claude-ab1","decision":"deny"}\n{"approval":7}\n')
            self.wait_for(lambda: pressed[2:] == [("claude-ab1", "deny")])

            app.handle_hook("claude", ev("Stop", "c"))  # state change: sent before the heartbeat
            self.wait_for(lambda: self.read_frame(master)["a"][0]["s"] == "done")
        finally:
            link.stop.set()
            device.has_pyserial = old
            time.sleep(0.4)
            os.close(master)
            os.close(slave)

    def read_frame(self, fd, timeout=5):
        import select
        buf, end = b"", time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                buf += os.read(fd, 4096)
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.startswith(b'{"v":1'):
                        return json.loads(line)
        self.fail("no frame from the daemon")

    def wait_for(self, cond, timeout=8, step=0.05):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(step)
        self.fail("condition not met")


if __name__ == "__main__":
    unittest.main()
