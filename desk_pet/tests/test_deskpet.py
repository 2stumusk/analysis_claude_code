import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deskpet import agents as registry  # noqa: E402
from deskpet import core, demo  # noqa: E402
from deskpet.core import Tracker, classify_tool  # noqa: E402
from deskpet.pet import Pet  # noqa: E402
from deskpet.server import App, serve  # noqa: E402
from deskpet.usage import ClaudeUsage  # noqa: E402


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def ev(name, sid="s1", **kw):
    return dict(hook_event_name=name, session_id=sid, **kw)


class ClassifyTest(unittest.TestCase):
    def test_known_tools(self):
        self.assertEqual(classify_tool("Bash", {"command": "npm test\nmore"}), ("running", "npm test"))
        self.assertEqual(classify_tool("Read", {"file_path": "/a/b/cart.ts"}), ("reading", "cart.ts"))
        self.assertEqual(classify_tool("Edit", {"file_path": "/a/x.py"}), ("editing", "x.py"))
        self.assertEqual(classify_tool("Grep", {"pattern": "TODO"}), ("reading", "TODO"))
        self.assertEqual(classify_tool("WebFetch", {"url": "https://docs.x.com/a"}), ("reading", "docs.x.com"))
        self.assertEqual(classify_tool("Task", {"description": "find bugs"}), ("thinking", "find bugs"))
        self.assertEqual(classify_tool("apply_patch", {"input": "..."}), ("editing", "patch"))

    def test_unknown_tools_by_shape(self):
        self.assertEqual(classify_tool("mystery_exec", {"command": ["ls", "-la"]})[0], "running")
        self.assertEqual(classify_tool("mcp__fs__write", {"path": "/r/a.md", "content": "x"}), ("editing", "a.md"))
        self.assertEqual(classify_tool("mcp__x__ping", {}), ("thinking", "mcp__x__ping"))

    def test_detail_is_clipped(self):
        state, detail = classify_tool("Bash", {"command": "x" * 200})
        self.assertLessEqual(len(detail), core.DETAIL_MAX)


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.done = []
        self.t = Tracker(clock=self.clock, on_task_done=lambda *a: self.done.append(a))

    def state(self, agent="claude"):
        return self.t.snapshot()["agents"][agent]

    def test_offline_until_first_event(self):
        snap = self.t.snapshot(["claude", "codex"])
        self.assertEqual(snap["agents"]["claude"]["state"], "offline")
        self.assertEqual(snap["agents"]["codex"]["state"], "offline")

    def test_task_lifecycle(self):
        self.t.handle("claude", ev("SessionStart", cwd="/work/shop"))
        self.assertEqual(self.state()["state"], "idle")
        self.assertEqual(self.state()["cwd"], "shop")
        self.t.handle("claude", ev("UserPromptSubmit"))
        self.assertEqual(self.state()["state"], "thinking")
        self.t.handle("claude", ev("PreToolUse", tool_name="Bash", tool_input={"command": "make"}))
        self.assertEqual((self.state()["state"], self.state()["detail"]), ("running", "make"))
        self.t.handle("claude", ev("PostToolUse", tool_name="Bash"))
        self.assertEqual(self.state()["state"], "thinking")
        self.clock.t += 90
        self.t.handle("claude", ev("Stop"))
        self.assertEqual(self.state()["state"], "done")
        self.assertEqual(self.done, [("claude", "done", 90, 1)])
        self.clock.t += core.DONE_HOLD + 1
        self.assertEqual(self.state()["state"], "idle")
        self.t.handle("claude", ev("SessionEnd"))
        self.assertEqual(self.state()["state"], "offline")

    def test_permission_request_waits_after_grace(self):
        self.t.handle("codex", ev("UserPromptSubmit"))
        self.t.handle("codex", ev("PermissionRequest", tool_name="Bash", tool_input={"command": "rm -rf build"}))
        self.assertEqual(self.state("codex")["state"], "thinking")  # may still be auto-approved
        self.clock.t += core.WAIT_GRACE
        s = self.state("codex")
        self.assertEqual((s["state"], s["alert"], s["detail"]), ("waiting", True, "rm -rf build"))
        self.t.handle("codex", ev("PreToolUse", tool_name="Bash", tool_input={"command": "rm -rf build"}))
        self.assertEqual(self.state("codex")["state"], "running")

    def test_auto_approved_permission_is_ignored(self):
        self.t.handle("codex", ev("PermissionRequest", permission_mode="bypassPermissions"))
        self.clock.t += 10
        self.assertNotEqual(self.state("codex")["state"], "waiting")

    def test_notification_permission_prompt_is_immediate(self):
        self.t.handle("claude", ev("Notification", notification_type="permission_prompt",
                                   message="Claude needs your permission to use Bash"))
        self.assertEqual(self.state()["state"], "waiting")

    def test_idle_prompt_notification_is_not_an_alert(self):
        self.t.handle("claude", ev("Notification", notification_type="idle_prompt",
                                   message="Claude is waiting for your input"))
        self.assertNotEqual(self.state()["state"], "waiting")

    def test_most_urgent_session_and_agent_win(self):
        self.t.handle("claude", ev("UserPromptSubmit", sid="a"))
        self.t.handle("claude", ev("Notification", sid="b", notification_type="permission_prompt"))
        self.t.handle("codex", ev("UserPromptSubmit"))
        snap = self.t.snapshot()
        self.assertEqual(snap["agents"]["claude"]["state"], "waiting")
        self.assertEqual(snap["agents"]["claude"]["sessions"], 2)
        self.assertEqual(snap["focus"], "claude")

    def test_ack_mutes_alert_then_clears_done(self):
        self.t.handle("claude", ev("Notification", notification_type="permission_prompt"))
        self.assertTrue(self.t.ack())
        s = self.state()
        self.assertEqual((s["state"], s["alert"]), ("waiting", False))
        self.t.handle("claude", ev("Stop"))
        self.assertTrue(self.t.ack())
        self.assertEqual(self.state()["state"], "idle")
        self.assertFalse(self.t.ack())

    def test_stop_failure_and_codex_notify(self):
        self.t.handle("codex", ev("StopFailure", error="2 tests failed"))
        self.assertEqual((self.state("codex")["state"], self.state("codex")["detail"]), ("error", "2 tests failed"))
        self.t.handle("codex", {"type": "agent-turn-complete", "thread-id": "t9"})
        self.assertEqual(self.done[-1][:2], ("codex", "done"))

    def test_garbage_payload_is_harmless(self):
        self.t.handle("claude", "not a dict")
        self.t.handle("claude", ev("PreToolUse", tool_name=None, tool_input="oops"))
        self.assertIn(self.state()["state"], core.PRIORITY)

    def test_stale_sessions_are_dropped(self):
        self.t.handle("claude", ev("SessionStart"))
        self.clock.t += core.SESSION_STALE + 1
        self.assertEqual(self.state()["state"], "offline")


    def test_gemini_events(self):
        self.t.handle("gemini", ev("BeforeAgent", prompt="fix it"))
        self.assertEqual(self.state("gemini")["state"], "thinking")
        self.t.handle("gemini", ev("BeforeTool", tool_name="run_shell_command",
                                   tool_input={"command": "pytest -q"}))
        self.assertEqual((self.state("gemini")["state"], self.state("gemini")["detail"]),
                         ("running", "pytest -q"))
        self.t.handle("gemini", ev("BeforeTool", tool_name="read_file",
                                   tool_input={"absolute_path": "/r/main.py"}))
        self.assertEqual(self.state("gemini")["detail"], "main.py")
        self.t.handle("gemini", ev("Notification", notification_type="ToolPermission"))
        self.assertEqual(self.state("gemini")["state"], "waiting")
        self.t.handle("gemini", ev("AfterAgent"))
        self.assertEqual(self.state("gemini")["state"], "done")

    def test_kimi_and_qwen_tool_names(self):
        self.assertEqual(classify_tool("Shell", {"command": "ls"})[0], "running")
        self.assertEqual(classify_tool("StrReplaceFile", {"path": "/a/b.ts"}), ("editing", "b.ts"))
        self.assertEqual(classify_tool("write_file", {"file_path": "/a/c.md", "content": ""}), ("editing", "c.md"))
        self.assertEqual(classify_tool("grep_search", {"pattern": "foo"}), ("reading", "foo"))

    def test_duplicate_stop_counts_once(self):
        self.t.handle("grok", ev("UserPromptSubmit"))
        self.t.handle("grok", ev("Stop"))
        self.clock.t += 1
        self.t.handle("grok", ev("Stop"))
        self.assertEqual(len(self.done), 1)


class IdentifyTest(unittest.TestCase):
    def test_rules(self):
        idf = registry.identify
        self.assertIsNone(idf("claude", {}, None))
        self.assertIsNone(idf("claude", {}, {"procs": ["sh", "claude", "zsh"]}))
        self.assertEqual(idf("claude", {}, {"procs": ["sh", "grok", "zsh"]}), "grok")
        self.assertEqual(idf("claude", {}, {"procs": ["claude"], "base_url_host": "api.deepseek.com"}), "deepseek")
        self.assertEqual(idf("claude", {}, {"base_url_host": "api.moonshot.cn"}), "kimi")
        self.assertEqual(idf("claude", {}, {"base_url_host": "dashscope.aliyuncs.com"}), "qwen")
        self.assertEqual(idf("claude", {"model": "deepseek-v4-pro"}, {}), "deepseek")
        self.assertEqual(idf("claude", {}, {"as": "deepseek", "procs": ["grok"]}), "deepseek")
        self.assertIsNone(idf("claude", {}, {"as": "not-an-agent"}))
        # A Claude ancestor stops the walk before an outer agent further up.
        self.assertIsNone(idf("claude", {}, {"procs": ["sh", "claude", "codex"]}))

    def test_app_routes_session_after_first_hint(self):
        app = App(usage=False)
        app.set_config({"agents": ["claude", "deepseek"]})
        app.handle_hook("claude", ev("SessionStart", sid="d1",
                                     _deskpet={"base_url_host": "api.deepseek.com"}))
        app.handle_hook("claude", ev("UserPromptSubmit", sid="d1"))  # e.g. no hints
        snap = app.snapshot()
        self.assertEqual(snap["agents"]["deepseek"]["state"], "thinking")
        self.assertEqual(snap["agents"]["claude"]["state"], "offline")
        self.assertEqual(snap["agents"]["deepseek"]["label"], "DEEPSEEK")
        app.handle_hook("claude", ev("SessionEnd", sid="d1"))
        self.assertEqual(app.routes, {})


class ConfigTest(unittest.TestCase):
    def test_custom_and_auto_modes_persist(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            app = App(usage=False, config_path=path)
            self.assertEqual(app.snapshot()["order"], ["claude", "codex"])
            app.set_config({"agents": ["qwen", "bogus", "kimi", "kimi"]})
            self.assertEqual(app.snapshot()["order"], ["qwen", "kimi"])  # registry order
            app.set_config({"agents": []})  # never allow an empty screen in custom mode
            self.assertEqual(app.config["agents"], ["qwen", "kimi"])
            app.set_config({"mode": "auto"})
            self.assertEqual(app.snapshot()["order"], [])
            app.handle_hook("grok", ev("UserPromptSubmit"))
            app.handle_hook("gemini", ev("BeforeAgent"))
            snap = app.snapshot()
            self.assertEqual(snap["order"], ["gemini", "grok"])
            self.assertEqual(snap["focus"], "grok" if snap["agents"]["grok"]["last"] > snap["agents"]["gemini"]["last"] else "gemini")
            again = App(usage=False, config_path=path)
            self.assertEqual(again.config, {"mode": "auto", "agents": ["qwen", "kimi"]})

    def test_hidden_agents_still_tracked(self):
        app = App(usage=False)
        app.handle_hook("kimi", ev("UserPromptSubmit"))
        self.assertNotIn("kimi", app.snapshot()["agents"])
        app.set_config({"agents": ["kimi"]})
        self.assertEqual(app.snapshot()["agents"]["kimi"]["state"], "thinking")


class HookConfigTest(unittest.TestCase):
    def test_every_agent_has_parseable_config(self):
        import tomllib
        for agent in registry.ORDER:
            path, text, notes = registry.hook_config(agent, 7878)
            self.assertTrue(path.startswith("~/"), agent)
            if path.endswith(".toml"):
                data = tomllib.loads(text)
                if agent == "kimi":
                    self.assertTrue(all(set(h) == {"event", "command", "timeout"} for h in data["hooks"]))
                else:
                    self.assertEqual(data["ui"]["notifications"]["hooks"][0]["only_unfocused"], False)
            else:
                data = json.loads(text)
                for entries in data["hooks"].values():
                    for e in entries:
                        self.assertIn("hook_bridge.py", e["hooks"][0]["command"])
        self.assertIn("BeforeTool", json.loads(registry.hook_config("gemini")[1])["hooks"])
        self.assertEqual(json.loads(registry.hook_config("gemini")[1])["hooks"]["BeforeTool"][0]["hooks"][0]["timeout"], 5000)

    def test_demo_casts_every_selected_agent(self):
        cast = ["kimi", "deepseek", "qwen", "grok"]
        tl = demo.timeline(cast)
        self.assertEqual({a for _, a, _ in tl}, set(cast))
        self.assertEqual([x[0] for x in tl], sorted(x[0] for x in tl))


class PetTest(unittest.TestCase):
    def test_xp_level_energy_and_persistence(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pet.json")
            pet = Pet(path, clock=clock)
            for _ in range(5):
                pet.task_done("claude", "done", 120, 30)
            snap = pet.snapshot()
            self.assertEqual(snap["xp"], 5 * (10 + 20 + 2))
            self.assertEqual(snap["level"], 2)
            self.assertIsNotNone(snap["levelup_at"])
            self.assertEqual(snap["tasks_today"], 5)
            clock.t += 15 * 60 * 40
            self.assertEqual(Pet(path, clock=clock).snapshot()["energy"], 100 - 40)
            pet.feed()
            self.assertEqual(Pet(path, clock=clock).snapshot()["energy"], 100 - 40 + 15)


class UsageTest(unittest.TestCase):
    def test_counts_today_and_dedupes(self):
        today = date(2026, 10, 26)
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "proj"))
            path = os.path.join(d, "proj", "s.jsonl")
            u = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                 "cache_creation_input_tokens": 7}
            lines = [
                {"timestamp": "2026-10-26T12:00:00", "requestId": "r1", "message": {"id": "m1", "usage": u}},
                {"timestamp": "2026-10-26T12:00:01", "requestId": "r1", "message": {"id": "m1", "usage": u}},
                {"timestamp": "2026-10-25T12:00:00", "requestId": "r0", "message": {"id": "m0", "usage": u}},
                {"timestamp": "2026-10-26T12:01:00", "type": "user", "message": {"content": "hi"}},
            ]
            with open(path, "w") as f:
                f.write("\n".join(json.dumps(x) for x in lines) + "\n")
                f.write('{"partial": ')  # incomplete trailing line is left for the next scan
            usage = ClaudeUsage(root=d, today=lambda: today)
            usage.scan()
            s = usage.snapshot()
            self.assertEqual((s["input"], s["output"], s["cache_read"], s["cache_write"], s["messages"]),
                             (10, 5, 100, 7, 1))
            with open(path, "a") as f:
                f.write('"x"}\n' + json.dumps({"timestamp": "2026-10-26T13:00:00", "requestId": "r2",
                                               "message": {"id": "m2", "usage": u}}) + "\n")
            usage.scan()
            self.assertEqual(usage.snapshot()["output"], 10)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app, cls.httpd = serve("127.0.0.1", 0, os.path.join(cls.tmp.name, "pet.json"), usage=False)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def req(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data,
                                   headers={"Content-Type": "application/json", **(headers or {})},
                                   method="POST" if data is not None else "GET")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(r, timeout=3) as resp:
            return resp.status, resp.read()

    def test_hook_then_state(self):
        status, body = self.req("/hook/claude", ev("UserPromptSubmit", sid="srv"))
        self.assertEqual((status, json.loads(body)), (200, {}))
        _, body = self.req("/api/state")
        snap = json.loads(body)
        self.assertEqual(snap["v"], 1)
        self.assertEqual(snap["agents"]["claude"]["state"], "thinking")
        self.assertIn("pet", snap)

    def test_event_from_query(self):
        self.req("/hook/codex?event=UserPromptSubmit", {"session_id": "q"})
        _, body = self.req("/api/state")
        self.assertEqual(json.loads(body)["agents"]["codex"]["state"], "thinking")

    def test_cross_origin_post_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.req("/hook/claude", ev("Stop"), headers={"Origin": "https://evil.example"})
        self.assertEqual(cm.exception.code, 403)

    def test_static_and_button(self):
        status, body = self.req("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<canvas", body)
        _, body = self.req("/api/button", {"button": "B"})
        self.assertIn(json.loads(body)["action"], ("ack", "feed"))

    def test_bad_json(self):
        r = urllib.request.Request("http://127.0.0.1:%d/hook/claude" % self.port, data=b"{nope",
                                   method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            opener.open(r, timeout=3)
        self.assertEqual(cm.exception.code, 400)

    def test_hook_bridge_forwards_and_stays_silent(self):
        bridge = os.path.join(ROOT, "hooks", "hook_bridge.py")
        payload = json.dumps(ev("PreToolUse", sid="bridge", tool_name="Bash", tool_input={"command": "ls"}))
        out = subprocess.run([sys.executable, bridge, "codex", "--port", str(self.port)],
                             input=payload.encode(), capture_output=True, timeout=10)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))
        _, body = self.req("/api/state")
        self.assertEqual(json.loads(body)["agents"]["codex"]["state"], "running")

    def test_hook_bridge_grok_env_mode(self):
        bridge = os.path.join(ROOT, "hooks", "hook_bridge.py")
        env = dict(os.environ, GROK_EVENT="approval_required", GROK_SESSION_ID="g1", GROK_MESSAGE="run rm?")
        out = subprocess.run([sys.executable, bridge, "grok", "--grok-env", "--port", str(self.port)],
                             capture_output=True, timeout=10, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))
        self.app.set_config({"agents": ["claude", "codex", "grok"]})
        try:
            _, body = self.req("/api/state")
            self.assertEqual(json.loads(body)["agents"]["grok"]["state"], "waiting")
        finally:
            self.app.set_config({"agents": ["claude", "codex"]})

    def test_hook_bridge_detects_deepseek_backend(self):
        bridge = os.path.join(ROOT, "hooks", "hook_bridge.py")
        env = dict(os.environ, ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic",
                   ANTHROPIC_AUTH_TOKEN="sk-secret")
        payload = json.dumps(ev("UserPromptSubmit", sid="ds-bridge")).encode()
        out = subprocess.run([sys.executable, bridge, "claude", "--port", str(self.port)],
                             input=payload, capture_output=True, timeout=10, env=env)
        self.assertEqual(out.returncode, 0)
        self.app.set_config({"agents": ["claude", "deepseek"]})
        try:
            _, body = self.req("/api/state")
            agents = json.loads(body)["agents"]
            self.assertEqual(agents["deepseek"]["state"], "thinking")
            self.assertNotIn("sk-secret", body.decode())
        finally:
            self.app.set_config({"agents": ["claude", "codex"]})

    def test_config_and_agents_api(self):
        _, body = self.req("/api/agents")
        catalog = json.loads(body)
        self.assertEqual([a["id"] for a in catalog], registry.ORDER)
        _, body = self.req("/api/config", {"agents": ["claude", "codex", "gemini"]})
        try:
            self.assertEqual(json.loads(body)["agents"], ["claude", "codex", "gemini"])
            _, body = self.req("/api/state")
            self.assertEqual(json.loads(body)["order"], ["claude", "codex", "gemini"])
        finally:
            self.req("/api/config", {"agents": ["claude", "codex"]})

    def test_hook_bridge_without_daemon_still_exits_zero(self):
        bridge = os.path.join(ROOT, "hooks", "hook_bridge.py")
        out = subprocess.run([sys.executable, bridge, "claude", "--port", "1"],
                             input=b"{}", capture_output=True, timeout=10)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))


if __name__ == "__main__":
    unittest.main()
