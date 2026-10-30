import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deskpet import agents as registry  # noqa: E402
from deskpet.approvals import Approvals, describe_request  # noqa: E402
from deskpet.device import device_frame, frame_key  # noqa: E402
from deskpet.server import App, serve  # noqa: E402

BRIDGE = os.path.join(ROOT, "hooks", "hook_bridge.py")


def ev(name, sid="s1", **kw):
    return dict(hook_event_name=name, session_id=sid, **kw)


def ask(sid="s1", command="rm -rf build", **kw):
    return ev("PermissionRequest", sid, tool_name="Bash", tool_input={"command": command}, **kw)


def decide_when_held(app, decision, timeout=5):
    """Answer the first request that shows up, the way a button press would."""
    def run():
        end = time.time() + timeout
        while time.time() < end:
            held = app.approvals.current()
            if held:
                app.decide(held.id, decision)
                return
            time.sleep(0.02)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class ApprovalsTest(unittest.TestCase):
    def test_decide_wakes_the_waiter(self):
        ap = Approvals()
        p = ap.open("claude", "s", "Bash", "ls", 5)
        self.assertIs(ap.current(), p)
        threading.Timer(0.05, ap.decide, (p.id, "allow")).start()
        self.assertEqual(ap.wait(p, 5), "allow")
        self.assertIsNone(ap.current())

    def test_unknown_stale_and_bad_decisions(self):
        ap = Approvals()
        p = ap.open("claude", "s", "Bash", "ls", 5)
        self.assertFalse(ap.decide("claude-0", "allow"))
        self.assertFalse(ap.decide(p.id, "yes"))
        self.assertTrue(ap.decide(p.id, "deny"))
        self.assertFalse(ap.decide(p.id, "allow"))  # already answered
        self.assertEqual(ap.wait(p, 0), "deny")

    def test_skip_and_timeout_give_no_decision(self):
        ap = Approvals()
        p = ap.open("codex", "s", "shell", "ls", 5)
        ap.decide(p.id, "skip")
        self.assertIsNone(ap.wait(p, 1))
        q = ap.open("codex", "s", "shell", "ls", 0.05)
        self.assertIsNone(ap.wait(q, 0.05))
        self.assertIsNone(ap.current())

    def test_oldest_live_request_first_and_ids_differ_per_run(self):
        t = [100.0]
        ap = Approvals(clock=lambda: t[0])
        first = ap.open("claude", "a", "Bash", "1", 10)
        second = ap.open("codex", "b", "shell", "2", 30)
        self.assertIs(ap.current(), first)
        t[0] = 111  # first one's deadline passed
        self.assertIs(ap.current(), second)
        self.assertNotEqual(Approvals().open("claude", "a", "Bash", "1", 5).id.split("-")[1],
                            first.id.split("-")[1])

    def test_cancel_session_only_touches_that_session(self):
        ap = Approvals()
        mine = ap.open("claude", "a", "Bash", "1", 5)
        other = ap.open("claude", "b", "Bash", "2", 5)
        self.assertEqual(ap.cancel_session("claude", "a"), 1)
        self.assertIsNone(ap.wait(mine, 0))
        self.assertIs(ap.current(), other)
        self.assertEqual(ap.cancel_all(), 1)
        self.assertIsNone(ap.current())

    def test_describe_request(self):
        self.assertEqual(describe_request("Bash", {"command": "npm  test\n--ci"}), "npm test --ci")
        self.assertEqual(describe_request("Write", {"file_path": "/a/b.txt", "content": "x"}), "/a/b.txt")
        self.assertEqual(describe_request("shell", {"command": ["bash", "-lc", "ls"]}), "bash -lc ls")
        self.assertEqual(describe_request("WebFetch", {"url": "https://x.dev"}), "https://x.dev")
        self.assertEqual(describe_request("mcp__x__y", {}), "mcp__x__y")
        self.assertEqual(len(describe_request("Bash", {"command": "x" * 500})), 120)


class AppApprovalTest(unittest.TestCase):
    def app(self, **config):
        app = App(usage=False, weather_factory=None)
        app.set_config(dict({"agents": ["claude", "codex"], "approvals": True, "approval_wait": 5}, **config))
        app.device = {"port": "/dev/fake", "board": "fake"}
        return app

    def test_off_by_default_and_without_a_screen(self):
        app = App(usage=False, weather_factory=None)
        self.assertFalse(app.config["approvals"])
        start = time.time()
        self.assertEqual(app.handle_hook_and_wait("claude", ask()), {})
        app.set_config({"approvals": True})  # on, but no device and no page open
        self.assertEqual(app.handle_hook_and_wait("claude", ask()), {})
        self.assertLess(time.time() - start, 1)

    def test_allow_and_deny(self):
        app = self.app()
        for decision in ("allow", "deny"):
            decide_when_held(app, decision)
            self.assertEqual(app.handle_hook_and_wait("claude", ask()), {"decision": decision})
            # The decision settles the alert on the pet as well.
            self.assertFalse(app.snapshot()["agents"]["claude"]["alert"])

    def test_timeout_and_skip_fall_back_to_the_computer(self):
        app = self.app()
        app.config["approval_wait"] = 0.2
        self.assertEqual(app.handle_hook_and_wait("codex", ask()), {})
        app.config["approval_wait"] = 5
        decide_when_held(app, "skip")
        self.assertEqual(app.handle_hook_and_wait("codex", ask()), {})
        # Still waiting on the computer's own prompt.
        self.assertEqual(app.snapshot()["agents"]["codex"]["state"], "waiting")

    def test_snapshot_shows_the_request_and_focuses_its_agent(self):
        app = self.app()
        app.handle_hook("claude", ev("PreToolUse", "c", tool_name="Bash", tool_input={"command": "ls"}))
        seen = {}

        def look():
            while not app.approvals.current():
                time.sleep(0.01)
            seen["snap"] = app.snapshot()
            app.decide(app.approvals.current().id, "deny")
        threading.Thread(target=look, daemon=True).start()
        app.handle_hook_and_wait("codex", ask("x", "cargo publish"))
        ap = seen["snap"]["approval"]
        self.assertEqual((ap["agent"], ap["label"], ap["tool"], ap["detail"], ap["wait"]),
                         ("codex", "CODEX", "Bash", "cargo publish", 5))
        self.assertEqual(seen["snap"]["focus"], "codex")
        self.assertIsNone(seen["snap"]["rotation"])
        frame = device_frame(seen["snap"])
        self.assertEqual((frame["ap"]["a"], frame["ap"]["l"], frame["ap"]["n"]), (1, "CODEX", 5))
        self.assertIsNone(app.snapshot()["approval"])
        self.assertNotEqual(frame_key(seen["snap"], frame),
                            frame_key(app.snapshot(), device_frame(app.snapshot())))

    def test_agent_moving_on_releases_the_request(self):
        app = self.app()
        threading.Timer(0.2, app.handle_hook, ("claude", ev("PostToolUse", "s1", tool_name="Bash"))).start()
        start = time.time()
        self.assertEqual(app.handle_hook_and_wait("claude", ask()), {})
        self.assertLess(time.time() - start, 2)

    def test_unplugging_the_device_releases_the_request(self):
        app = self.app()
        threading.Timer(0.2, app.set_device, (None,)).start()
        start = time.time()
        self.assertEqual(app.handle_hook_and_wait("claude", ask()), {})
        self.assertLess(time.time() - start, 2)

    def test_only_documented_agents_and_modes_are_held(self):
        app = self.app()
        start = time.time()
        self.assertEqual(app.handle_hook_and_wait("kimi", ask()), {})  # Kimi Code's own hooks
        self.assertEqual(app.handle_hook_and_wait("claude", ask(permission_mode="bypassPermissions")), {})
        grok = dict(ask("g"), _deskpet={"procs": ["bash", "grok"]})  # Grok running Claude's hooks
        self.assertEqual(app.handle_hook_and_wait("claude", grok), {})
        self.assertLess(time.time() - start, 1)
        # Claude Code on DeepSeek's API is still Claude Code.
        decide_when_held(app, "allow")
        ds = dict(ask("d"), _deskpet={"base_url_host": "api.deepseek.com"})
        self.assertEqual(app.handle_hook_and_wait("claude", ds), {"decision": "allow"})

    def test_config_bounds(self):
        app = App(usage=False, weather_factory=None)
        app.set_config({"approval_wait": 600})
        self.assertEqual(app.config["approval_wait"], 60)
        app.set_config({"approval_wait": 1})
        self.assertEqual(app.config["approval_wait"], 5)
        app.set_config({"approval_wait": True, "approvals": "yes"})
        self.assertEqual((app.config["approval_wait"], app.config["approvals"]), (5, False))

    def test_hook_config_gives_permission_requests_time(self):
        for agent in ("claude", "codex"):
            cfg = json.loads(registry.hook_config(agent)[1])["hooks"]
            self.assertEqual(cfg["PermissionRequest"][0]["hooks"][0]["timeout"], registry.APPROVAL_TIMEOUT)
            self.assertEqual(cfg["PreToolUse"][0]["hooks"][0]["timeout"], 5)


class BridgeTest(unittest.TestCase):
    """hooks/hook_bridge.py against a live daemon, as Claude Code / Codex would run it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app, cls.httpd = serve("127.0.0.1", 0, os.path.join(cls.tmp.name, "pet.json"), usage=False)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.app.set_config({"approvals": True, "approval_wait": 5})
        cls.app.device = {"port": "/dev/fake", "board": "fake"}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def bridge(self, agent, payload):
        return subprocess.run([sys.executable, BRIDGE, agent, "--port", str(self.port)],
                              input=json.dumps(payload).encode(), capture_output=True, timeout=30)

    def test_prints_the_documented_decision(self):
        decide_when_held(self.app, "allow")
        out = self.bridge("claude", ask("b1"))
        self.assertEqual((out.returncode, out.stderr), (0, b""))
        self.assertEqual(json.loads(out.stdout), {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}})

        decide_when_held(self.app, "deny")
        out = self.bridge("codex", ask("b2"))
        decision = json.loads(out.stdout)["hookSpecificOutput"]["decision"]
        # Codex fails closed on interrupt / updatedInput, so neither is ever sent.
        self.assertEqual(set(decision), {"behavior", "message"})
        self.assertEqual(decision["behavior"], "deny")

    def test_no_decision_prints_nothing(self):
        decide_when_held(self.app, "skip")
        out = self.bridge("claude", ask("b3"))
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))
        # Other events never wait.
        start = time.time()
        out = self.bridge("claude", ev("PreToolUse", "b3", tool_name="Bash", tool_input={"command": "ls"}))
        self.assertEqual((out.returncode, out.stdout), (0, b""))
        self.assertLess(time.time() - start, 3)

    def test_answer_over_http(self):
        def press():
            while not self.app.approvals.current():
                time.sleep(0.02)
            rid = json.loads(self.get("/api/state"))["approval"]["id"]
            self.post("/api/approval", {"id": "nope", "decision": "allow"})
            self.post("/api/approval", {"id": rid, "decision": "deny"})
        threading.Thread(target=press, daemon=True).start()
        out = self.bridge("claude", ask("b4"))
        self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")

    def get(self, path):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open("http://127.0.0.1:%d%s" % (self.port, path), timeout=3).read()

    def post(self, path, body):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return json.loads(opener.open(r, timeout=3).read())


if __name__ == "__main__":
    unittest.main()
