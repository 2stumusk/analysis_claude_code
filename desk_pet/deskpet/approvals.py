"""Approve or deny agent permission requests from the desk pet's buttons.

Opt-in. When it is on and a screen is watching (the USB device, or the web
simulator), a PermissionRequest hook from Claude Code or Codex is held here for
up to `wait` seconds. The screen shows the request; A denies, B allows, C hands
it back to the computer. Without a decision in time the hook returns nothing
and the agent shows its normal permission prompt, so the computer always stays
the fallback.

hooks/hook_bridge.py turns the decision into the agent's documented
PermissionRequest output (Claude Code hooks reference; codex-rs/hooks
permission-request output schema). Deny rules the user configured still apply
on top of an "allow".
"""

import itertools
import os
import threading
import time

# Hook endpoint -> agents it may be routed to whose PermissionRequest output
# format is documented: Codex, and Claude Code itself, also when it runs on a
# DeepSeek/Kimi/Qwen API. Grok also runs Claude Code's hooks; it is left out.
SUPPORTED = {"claude": {"claude", "deepseek", "kimi", "qwen"}, "codex": {"codex"}}
DEFAULT_WAIT = 30
MIN_WAIT, MAX_WAIT = 5, 60
DETAIL_MAX = 120


def describe_request(tool, tool_input):
    """What the screen shows for a request: the command, the file, or the URL.
    Longer than the usual status detail, since it is what gets approved."""
    inp = tool_input if isinstance(tool_input, dict) else {}
    for key in ("command", "cmd", "file_path", "path", "notebook_path", "url", "pattern", "query"):
        value = inp.get(key)
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        if value:
            text = " ".join(str(value).split())
            return text if len(text) <= DETAIL_MAX else text[:DETAIL_MAX - 3] + "..."
    return str(tool or "tool")


class Pending:
    def __init__(self, rid, agent, session, tool, detail, deadline):
        self.id = rid
        self.agent = agent
        self.session = session
        self.tool = tool
        self.detail = detail
        self.deadline = deadline
        self.decision = None
        self.done = threading.Event()


class Approvals:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.pending = {}  # id -> Pending, oldest first
        self.ids = itertools.count(1)
        self.run = os.urandom(2).hex()  # ids from an earlier daemon run never match

    def open(self, agent, session, tool, detail, wait):
        with self.lock:
            rid = "%s-%s%d" % (agent, self.run, next(self.ids))
            p = Pending(rid, agent, session, tool, detail, self.clock() + wait)
            p.wait = wait
            self.pending[rid] = p
            return p

    def wait(self, p, timeout):
        """Block until a decision or the timeout; returns 'allow', 'deny' or None."""
        p.done.wait(timeout)
        with self.lock:
            self.pending.pop(p.id, None)
        return p.decision if p.decision in ("allow", "deny") else None

    def decide(self, rid, decision):
        """'allow', 'deny', or 'skip' (leave it to the computer). False if unknown or stale."""
        if decision not in ("allow", "deny", "skip"):
            return False
        with self.lock:
            p = self.pending.pop(rid, None)
        if p is None:
            return False
        p.decision = decision
        p.done.set()
        return True

    def cancel_session(self, agent, session):
        """The agent moved on (the person answered on the computer, or the turn
        ended): stop holding that session's requests. Returns how many."""
        with self.lock:
            gone = [p for p in self.pending.values() if p.agent == agent and p.session == session]
            for p in gone:
                self.pending.pop(p.id, None)
        for p in gone:
            p.decision = "skip"
            p.done.set()
        return len(gone)

    def cancel_all(self):
        """Nobody can answer any more: hand every held request back."""
        with self.lock:
            gone = list(self.pending.values())
            self.pending.clear()
        for p in gone:
            p.decision = "skip"
            p.done.set()
        return len(gone)

    def current(self):
        """The oldest request still waiting, or None."""
        now = self.clock()
        with self.lock:
            for p in self.pending.values():
                if p.deadline > now and not p.done.is_set():
                    return p
        return None
