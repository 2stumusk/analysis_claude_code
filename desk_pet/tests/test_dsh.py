import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deskpet import agents as registry  # noqa: E402
from deskpet.core import Tracker, classify_tool  # noqa: E402
from deskpet.server import serve  # noqa: E402

PLUGIN = os.path.join(ROOT, "integrations", "dsh", "index.js")


class DshToolsTest(unittest.TestCase):
    def test_tool_names(self):
        self.assertEqual(classify_tool("bash", {"description": "x", "command": "pytest -q"}), ("running", "pytest -q"))
        self.assertEqual(classify_tool("run_code", {"code": "print(1)"})[0], "running")
        self.assertEqual(classify_tool("read", {"file_path": "/r/app.py"}), ("reading", "app.py"))
        self.assertEqual(classify_tool("write", {"file_path": "/r/new.py", "content": ""}), ("editing", "new.py"))
        self.assertEqual(classify_tool("str_replace_editor", {"command": "view", "path": "/r/src"}), ("reading", "src"))
        self.assertEqual(classify_tool("str_replace_editor", {"command": "str_replace", "path": "/r/a.py",
                                                              "old_str": "x", "new_str": "y"}), ("editing", "a.py"))

    def test_questions_need_the_human(self):
        t = Tracker()
        t.handle("dsh", {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "ask_user_question",
                         "tool_input": {"question": "which db?"}})
        a = t.snapshot(["dsh"])["agents"]["dsh"]
        self.assertEqual((a["state"], a["alert"], a["detail"]), ("waiting", True, "question for you"))

    def test_registry(self):
        self.assertIn("dsh", registry.PRESETS["china"])
        path, text, notes = registry.hook_config("dsh", 9000)
        self.assertIn("export DESKPET_PORT=9000", text)
        self.assertIn("dsh plugin --profile tui add " + os.path.dirname(PLUGIN), text)
        with open(os.path.join(os.path.dirname(PLUGIN), "package.json")) as f:
            pkg = json.load(f)
        self.assertEqual(pkg["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertEqual(registry.identify("dsh", {}, {"procs": ["node", "dsh"]}), "dsh")


DRIVER = r"""
import * as plugin from %(plugin)s
const handlers = {}
const ctx = { on: (name, fn) => { handlers[name] = fn } }
plugin.apply(ctx)
const session = { id: 'sess-1', header: { cwd: '/work/shop-api' } }
const emit = (type, data) => handlers['session/event'](session, { type, seq: 0, time: 0, data })
const steps = JSON.parse(process.argv[2])
for (const [type, data] of steps) {
  if (type === 'dispose') handlers['session/disposed'](session)
  else emit(type, data)
}
// let the ordered post queue drain
await new Promise(r => setTimeout(r, 1500))
"""


@unittest.skipUnless(shutil.which("node"), "needs Node.js 18+")
class DshPluginTest(unittest.TestCase):
    """Load the real plugin in Node and send its posts to a real daemon."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app, cls.httpd = serve("127.0.0.1", 0, os.path.join(cls.tmp.name, "pet.json"), usage=False)
        cls.app.weather_factory = None
        cls.app.set_config({"agents": ["dsh"]})
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.driver = os.path.join(cls.tmp.name, "driver.mjs")
        with open(cls.driver, "w") as f:
            f.write(DRIVER % {"plugin": json.dumps("file://" + PLUGIN)})

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def run_steps(self, steps):
        env = dict(os.environ, DESKPET_PORT=str(self.port), NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
        out = subprocess.run(["node", self.driver, json.dumps(steps)], capture_output=True, text=True,
                             timeout=30, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return self.app.snapshot()["agents"]["dsh"]

    def test_turn_lifecycle(self):
        a = self.run_steps([["turn/start", {"turn": 1}],
                            ["tool/call", {"turn": 1, "step": 1, "callId": "c1", "name": "bash",
                                           "arguments": json.dumps({"description": "run tests", "command": "pnpm test"})}]])
        self.assertEqual((a["state"], a["detail"], a["cwd"]), ("running", "pnpm test", "shop-api"))
        a = self.run_steps([["tool/result", {"callId": "c1"}],
                            ["approval/asked", {"id": "q1", "toolName": "bash"}]])
        self.assertIn(a["state"], ("thinking", "waiting"))  # waiting after the 1.5 s grace
        a = self.run_steps([["approval/decided", {"id": "q1", "outcome": "allowed-once"}],
                            ["turn/end", {"turn": 1, "reason": {"kind": "completed"}}]])
        self.assertEqual(a["state"], "done")
        a = self.run_steps([["turn/start", {"turn": 2}],
                            ["turn/end", {"turn": 2, "reason": {"kind": "error", "error": {"message": "rate limited"}}}]])
        self.assertEqual((a["state"], a["detail"]), ("error", "rate limited"))
        a = self.run_steps([["turn/end", {"turn": 3, "reason": {"kind": "forked"}}], ["dispose", None]])
        self.assertEqual(a["state"], "offline")

    def test_bad_arguments_and_no_daemon(self):
        a = self.run_steps([["tool/call", {"name": "str_replace_editor", "arguments": "{not json"}]])
        self.assertEqual(a["state"], "editing")  # unparsable arguments: tool name still classifies
        env = dict(os.environ, DESKPET_PORT="1")
        out = subprocess.run(["node", self.driver, json.dumps([["turn/start", {"turn": 1}]])],
                             capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual((out.returncode, out.stderr), (0, ""))  # unreachable daemon is silent


if __name__ == "__main__":
    unittest.main()
