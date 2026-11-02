"""Bring the terminal an agent runs in to the front (macOS).

Pressing B on an agent that needs you (or just finished) also switches the
Mac to the window and tab it runs in, so you don't have to hunt for it.

How the terminal is found: hooks/hook_bridge.py sends the hook's controlling
tty (from `ps`) and the app it was started from (__CFBundleIdentifier, which
macOS puts in the environment of every process an app launches). For
Terminal.app and iTerm2, an AppleScript finds the tab whose `tty` matches and
selects it (both apps' scripting dictionaries have a tab / session `tty`
property); any other app (VS Code, Cursor, Warp, Ghostty...) is just brought
to the front with `open -b`. Same approach as atarnvik/ccradar and
Neilos/claude-code-hooks.

The tty and bundle id are checked against strict patterns and passed to
osascript as arguments, never pasted into script text. macOS asks once for
permission to let Python control Terminal / iTerm2 (Automation).
"""

import re
import subprocess
import sys
import threading

TTY_RE = re.compile(r"^/dev/tty[a-z]*[0-9]+$")
BUNDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,99}$")
TERMINAL = "com.apple.Terminal"
ITERM = "com.googlecode.iterm2"
NOTE_STATES = ("waiting", "done", "error")  # pressing B on these also jumps

SCRIPTS = {
    TERMINAL: """on run argv
  set target to item 1 of argv
  tell application "Terminal"
    repeat with w in windows
      repeat with t in tabs of w
        if tty of t is target then
          set selected of t to true
          set index of w to 1
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end tell
  return "missing"
end run""",
    ITERM: """on run argv
  set target to item 1 of argv
  tell application id "com.googlecode.iterm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if tty of s is target then
            select w
            select t
            try
              select s
            end try
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "missing"
end run""",
}


def clean(hints):
    """{"tty", "app"} from the bridge's hints, keeping only well-formed values."""
    if not isinstance(hints, dict):
        return None
    tty = hints.get("tty") if isinstance(hints.get("tty"), str) and TTY_RE.match(hints["tty"]) else None
    app = hints.get("app") if isinstance(hints.get("app"), str) and BUNDLE_RE.match(hints["app"]) else None
    return {"tty": tty, "app": app} if tty or app else None


def commands(where):
    """What to run, in order, until one works: the precise tab switch, then the app."""
    if not where:
        return []
    out = []
    if where.get("tty") and where.get("app") in SCRIPTS:
        out.append(["osascript", "-e", SCRIPTS[where["app"]], where["tty"]])
    if where.get("app"):
        out.append(["open", "-b", where["app"]])
    return out


class Jumper:
    def __init__(self, runner=subprocess.run, platform=sys.platform, background=True):
        self.runner = runner
        self.platform = platform
        self.background = background
        self.last = None  # outcome of the latest jump, for the panel / tests

    def supported(self):
        return self.platform == "darwin"

    def jump(self, where):
        """Start switching to `where`; returns at once ("started", "unknown" or "unsupported")."""
        if not self.supported():
            return "unsupported"
        cmds = commands(where)
        if not cmds:
            return "unknown"
        if self.background:
            threading.Thread(target=self._run, args=(cmds,), daemon=True).start()
        else:
            self._run(cmds)
        return "started"

    def _run(self, cmds):
        for argv in cmds:
            try:
                out = self.runner(argv, capture_output=True, text=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                continue
            if out.returncode == 0 and (argv[0] != "osascript" or out.stdout.strip() == "ok"):
                self.last = argv[0]
                return
        self.last = "failed"
