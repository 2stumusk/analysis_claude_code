import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hooks"))

import hook_bridge  # noqa: E402
from deskpet import jump  # noqa: E402
from deskpet.device import device_frame, frame_key  # noqa: E402
from deskpet.server import App  # noqa: E402


def ev(name, sid="s1", **kw):
    return dict(hook_event_name=name, session_id=sid, **kw)


class FakeRun:
    """Stands in for subprocess.run: records argv, answers from a script."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        code, out = self.answers.pop(0) if self.answers else (0, "")
        return subprocess.CompletedProcess(argv, code, out, "")


class JumpRulesTest(unittest.TestCase):
    def test_clean_keeps_only_well_formed_values(self):
        self.assertEqual(jump.clean({"tty": "/dev/ttys003", "app": "com.apple.Terminal"}),
                         {"tty": "/dev/ttys003", "app": "com.apple.Terminal"})
        self.assertEqual(jump.clean({"tty": "/dev/ttys003; rm -rf ~", "app": 'x" & do shell script "y'}), None)
        self.assertEqual(jump.clean({"tty": "/dev/pts/3"}), None)  # Linux ptys: not used
        self.assertEqual(jump.clean({"app": "com.microsoft.VSCode"}), {"tty": None, "app": "com.microsoft.VSCode"})
        self.assertIsNone(jump.clean("nope"))

    def test_commands(self):
        term = jump.commands({"tty": "/dev/ttys003", "app": "com.apple.Terminal"})
        self.assertEqual(term[0][:2], ["osascript", "-e"])
        self.assertEqual(term[0][3], "/dev/ttys003")       # passed as an argument, not in the script
        self.assertNotIn("ttys003", term[0][2])
        self.assertEqual(term[1], ["open", "-b", "com.apple.Terminal"])
        self.assertIn('tell application id "com.googlecode.iterm2"',
                      jump.commands({"tty": "/dev/ttys1", "app": "com.googlecode.iterm2"})[0][2])
        self.assertEqual(jump.commands({"tty": "/dev/ttys1", "app": "com.microsoft.VSCode"}),
                         [["open", "-b", "com.microsoft.VSCode"]])
        self.assertEqual(jump.commands({"tty": "/dev/ttys1", "app": None}), [])
        self.assertEqual(jump.commands(None), [])

    def test_jumper_falls_back_to_the_app(self):
        run = FakeRun([(0, "missing\n"), (0, "")])  # tab not found (e.g. inside tmux): bring the app forward
        j = jump.Jumper(runner=run, platform="darwin", background=False)
        self.assertEqual(j.jump({"tty": "/dev/ttys003", "app": "com.apple.Terminal"}), "started")
        self.assertEqual([c[0] for c in run.calls], ["osascript", "open"])
        self.assertEqual(j.last, "open")
        run = FakeRun([(0, "ok\n")])
        j = jump.Jumper(runner=run, platform="darwin", background=False)
        j.jump({"tty": "/dev/ttys003", "app": "com.googlecode.iterm2"})
        self.assertEqual((len(run.calls), j.last), (1, "osascript"))

    def test_jumper_elsewhere_does_nothing(self):
        run = FakeRun([])
        self.assertEqual(jump.Jumper(runner=run, platform="linux").jump({"app": "x.y"}), "unsupported")
        self.assertEqual(jump.Jumper(runner=run, platform="darwin").jump(None), "unknown")
        self.assertEqual(run.calls, [])


class JumpOnButtonTest(unittest.TestCase):
    def setUp(self):
        self.app = App(usage=False, weather_factory=None)
        self.app.set_config({"agents": ["claude", "codex"]})
        self.jumps = []
        self.app.jumper.jump = lambda where: self.jumps.append(where) or "started"
        self.where = {"tty": "/dev/ttys004", "app": "com.googlecode.iterm2"}
        self.app.handle_hook("claude", dict(ev("SessionStart", "a"), _deskpet=self.where))
        self.app.handle_hook("claude", dict(ev("SessionStart", "b"), _deskpet={"tty": "/dev/ttys009",
                                                                             "app": "com.apple.Terminal"}))

    def test_b_on_a_waiting_agent_jumps_to_that_session(self):
        self.app.handle_hook("claude", ev("Notification", "a", notification_type="permission_prompt"))
        self.assertEqual(self.app.button("B", "claude"), "ack")
        self.assertEqual(self.jumps, [self.where])

    def test_done_jumps_feed_and_ack_all_do_not(self):
        self.app.handle_hook("claude", ev("UserPromptSubmit", "b"))
        self.app.handle_hook("claude", ev("Stop", "b"))
        self.app.button("B", "claude")
        self.assertEqual(self.jumps, [{"tty": "/dev/ttys009", "app": "com.apple.Terminal"}])
        self.assertEqual(self.app.button("B", "claude"), "feed")  # nothing left to acknowledge
        self.app.handle_hook("claude", ev("Notification", "a", notification_type="permission_prompt"))
        self.app.button("B", everyone=True)
        self.assertEqual(len(self.jumps), 1)

    def test_switched_off(self):
        self.app.set_config({"jump": False})
        self.app.handle_hook("claude", ev("Notification", "a", notification_type="permission_prompt"))
        self.app.button("B", "claude")
        self.assertEqual(self.jumps, [])

    def test_session_end_forgets_the_terminal(self):
        self.assertIn(("claude", "a"), self.app.terminals)
        self.app.handle_hook("claude", ev("SessionEnd", "a"))
        self.assertNotIn(("claude", "a"), self.app.terminals)


class NudgeTest(unittest.TestCase):
    def test_alert_turns_urgent_after_the_reminder_time(self):
        app = App(usage=False, weather_factory=None)
        app.set_config({"agents": ["claude"], "nudge": 60})
        app.handle_hook("claude", ev("Notification", "s", notification_type="permission_prompt"))
        snap = app.snapshot()
        self.assertEqual((snap["agents"]["claude"]["alert"], snap["agents"]["claude"]["urgent"]), (True, False))
        frame = device_frame(snap)
        self.assertEqual((frame["a"][0]["u"], frame["a"][0]["w"]), (0, 0))

        app.tracker.agents["claude"]["s"].wait_at -= 61  # a minute later
        late = app.snapshot()
        self.assertTrue(late["agents"]["claude"]["urgent"])
        frame2 = device_frame(late)
        self.assertEqual(frame2["a"][0]["u"], 1)
        self.assertGreaterEqual(frame2["a"][0]["w"], 60)  # whole seconds, rounded down
        self.assertNotEqual(frame_key(snap, frame), frame_key(late, frame2))  # sent right away

        app.button("B", "claude")  # acknowledged: no longer an alert, so not urgent
        self.assertFalse(app.snapshot()["agents"]["claude"]["urgent"])

    def test_off_and_bad_values(self):
        app = App(usage=False, weather_factory=None)
        app.set_config({"agents": ["claude"], "nudge": 0})
        app.handle_hook("claude", ev("Notification", "s", notification_type="permission_prompt"))
        app.tracker.agents["claude"]["s"].wait_at -= 3600
        self.assertFalse(app.snapshot()["agents"]["claude"]["urgent"])
        app.set_config({"nudge": 7})
        app.set_config({"nudge": True})
        self.assertEqual(app.config["nudge"], 0)

    def test_waiting_seconds_only_while_waiting(self):
        app = App(usage=False, weather_factory=None)
        app.set_config({"agents": ["claude"]})
        app.handle_hook("claude", ev("UserPromptSubmit", "s"))
        self.assertEqual(device_frame(app.snapshot())["a"][0]["w"], -1)


class BridgeHintsTest(unittest.TestCase):
    def test_first_tty_walks_up_to_a_terminal(self):
        table = {30: (20, "??", ["python3"]), 20: (10, "ttys003", ["claude"]), 10: (1, "ttys003", ["zsh"])}
        self.assertEqual(hook_bridge._first_tty(table, 30), "/dev/ttys003")
        self.assertIsNone(hook_bridge._first_tty({30: (1, "??", ["x"])}, 30))
        self.assertIsNone(hook_bridge._first_tty({}, 30))

    def test_app_bundle_id_from_environment(self):
        os.environ["__CFBundleIdentifier"] = "com.apple.Terminal"
        try:
            self.assertEqual(hook_bridge.hints(None).get("app"), "com.apple.Terminal")
        finally:
            del os.environ["__CFBundleIdentifier"]
        self.assertNotIn("app", hook_bridge.hints(None))


if __name__ == "__main__":
    unittest.main()
