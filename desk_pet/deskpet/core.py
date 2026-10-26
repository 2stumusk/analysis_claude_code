"""Turn Claude Code / Codex hook events into a per-agent display state.

Each agent (claude, codex, ...) can have several live sessions. A session holds
its own state; the agent shows the most urgent session, and the screen focuses
on the most urgent agent.
"""

import os
import threading
import time
from urllib.parse import urlparse

# Display states, most urgent first.
PRIORITY = {
    "waiting": 90,
    "error": 80,
    "running": 60,
    "editing": 60,
    "reading": 60,
    "thinking": 50,
    "done": 40,
    "idle": 20,
    "offline": 0,
}
BUSY = {"thinking", "reading", "editing", "running"}

READ_TOOLS = {
    "Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "NotebookRead",
    "read_file", "list_dir", "grep", "glob", "web_search", "view_image",
}
EDIT_TOOLS = {
    "Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch", "edit",
    "write_file",
}
RUN_TOOLS = {
    "Bash", "BashOutput", "KillShell", "PowerShell", "shell", "exec_command",
    "local_shell", "unified_exec",
}
DELEGATE_TOOLS = {"Task", "Agent"}

# Notification types that mean "a human has to look at the screen now".
ATTENTION_NOTIFICATIONS = {
    "permission_prompt", "elicitation_dialog", "elicitation_url_dialog",
    "agent_needs_input",
}
# Permission modes in which a PermissionRequest never reaches the user.
AUTO_APPROVE_MODES = {"bypassPermissions", "dontAsk", "autoApproved", "approved"}
PERMISSION_RESOLVED = {
    "PermissionGranted", "PermissionApproved", "PermissionDenied",
    "PermissionRejected",
}

DONE_HOLD = 45          # seconds a "done"/"error" face stays before going idle
WAIT_GRACE = 1.5        # auto-approved requests resolve within this window
BUSY_STALE = 20 * 60    # a busy session with no events for this long is idle
SESSION_STALE = 60 * 60  # an idle session with no events for this long is gone
DETAIL_MAX = 48


def _clip(text, limit=DETAIL_MAX):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def classify_tool(tool_name, tool_input):
    """Return (state, detail) for a tool call."""
    name = tool_name or ""
    inp = tool_input if isinstance(tool_input, dict) else {}
    path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")

    if name in RUN_TOOLS or (name not in READ_TOOLS | EDIT_TOOLS and "command" in inp):
        cmd = inp.get("command", "")
        if isinstance(cmd, list):
            cmd = " ".join(map(str, cmd))
        return "running", _clip(str(cmd).strip().splitlines()[0] if str(cmd).strip() else name)
    if name in EDIT_TOOLS or (path and ("content" in inp or "old_string" in inp)):
        if not path and name == "apply_patch":
            return "editing", "patch"
        return "editing", _clip(os.path.basename(str(path)) if path else name)
    if name in DELEGATE_TOOLS:
        return "thinking", _clip(inp.get("description") or "subagent")
    if name in READ_TOOLS or path or "pattern" in inp or "query" in inp or "url" in inp:
        if path:
            return "reading", _clip(os.path.basename(str(path).rstrip("/")) or path)
        if inp.get("pattern"):
            return "reading", _clip(inp["pattern"])
        if inp.get("url"):
            return "reading", _clip(urlparse(str(inp["url"])).hostname or inp["url"])
        if inp.get("query"):
            return "reading", _clip(inp["query"])
        return "reading", name
    return "thinking", _clip(name) if name else ""


class Session:
    def __init__(self, sid, now):
        self.sid = sid
        self.state = "idle"
        self.detail = ""
        self.since = now
        self.last = now
        self.task_start = None
        self.tools = 0
        self.cwd = ""
        self.wait_at = None
        self.muted = False

    def set(self, state, detail=None, now=None):
        if state != self.state:
            self.since = now
        self.state = state
        if detail is not None:
            self.detail = detail

    def effective(self, now):
        if self.wait_at is not None and now >= self.wait_at:
            return "waiting"
        if self.state in ("done", "error") and now - self.since > DONE_HOLD:
            return "idle"
        if self.state in BUSY and now - self.last > BUSY_STALE:
            return "idle"
        return self.state


class Tracker:
    """Thread-safe store of agent sessions, fed by hook payloads."""

    def __init__(self, agents=("claude", "codex"), clock=time.time, on_task_done=None):
        self.clock = clock
        self.on_task_done = on_task_done
        self.lock = threading.RLock()
        self.agents = {a: {} for a in agents}

    def handle(self, agent, payload, event=None):
        """Apply one hook payload. Returns the event name that was used."""
        payload = payload if isinstance(payload, dict) else {}
        ev = event or payload.get("hook_event_name") or payload.get("type") or ""
        sid = str(payload.get("session_id") or payload.get("thread-id")
                  or payload.get("thread_id") or "default")
        now = self.clock()
        finished = None

        with self.lock:
            sessions = self.agents.setdefault(agent, {})
            if ev == "SessionEnd":
                sessions.pop(sid, None)
                return ev
            s = sessions.get(sid)
            if s is None:
                s = sessions[sid] = Session(sid, now)
            s.last = now
            if payload.get("cwd"):
                s.cwd = os.path.basename(str(payload["cwd"]).rstrip("/\\"))

            if ev == "SessionStart":
                s.wait_at = None
                s.set("idle", "", now)
            elif ev == "UserPromptSubmit":
                s.wait_at = None
                s.task_start, s.tools = now, 0
                s.set("thinking", "", now)
            elif ev == "PreToolUse":
                s.wait_at = None
                s.tools += 1
                if s.task_start is None:
                    s.task_start = now
                state, detail = classify_tool(payload.get("tool_name"), payload.get("tool_input"))
                s.set(state, detail, now)
            elif ev in ("PostToolUse", "PostToolUseFailure", "PostToolBatch",
                        "SubagentStop", "PostCompact") or ev in PERMISSION_RESOLVED:
                s.wait_at = None
                if s.state not in ("done", "idle"):
                    s.set("thinking", None, now)
            elif ev in ("SubagentStart", "PreCompact"):
                s.set("thinking", "subagent" if ev == "SubagentStart" else "compacting", now)
            elif ev == "PermissionRequest":
                if payload.get("permission_mode") not in AUTO_APPROVE_MODES:
                    if payload.get("tool_name"):
                        s.detail = classify_tool(payload.get("tool_name"), payload.get("tool_input"))[1]
                    s.wait_at, s.muted = now + WAIT_GRACE, False
            elif ev == "Notification":
                kind = payload.get("notification_type") or ""
                msg = str(payload.get("message") or "")
                if kind in ATTENTION_NOTIFICATIONS or (not kind and "permission" in msg.lower()):
                    s.wait_at, s.muted = now, False
                    if msg and not s.detail:
                        s.detail = _clip(msg)
                elif kind == "agent_completed":
                    finished = self._finish(s, "done", now)
            elif ev in ("Stop", "agent-turn-complete"):
                finished = self._finish(s, "done", now)
            elif ev == "StopFailure":
                finished = self._finish(s, "error", now)
                s.detail = _clip(payload.get("error") or payload.get("message") or "failed")
            elif ev == "Interrupt":
                s.wait_at = None
                s.task_start = None
                s.set("idle", "", now)

        if finished and self.on_task_done:
            self.on_task_done(agent, *finished)
        return ev

    def _finish(self, s, state, now):
        duration = now - s.task_start if s.task_start else 0
        tools = s.tools
        s.wait_at = None
        s.task_start = None
        s.set(state, "", now)
        return state, duration, tools

    def ack(self):
        """Button B: clear finished faces and silence pending alerts.

        Returns True when there was something to acknowledge."""
        now = self.clock()
        acted = False
        with self.lock:
            for sessions in self.agents.values():
                for s in sessions.values():
                    eff = s.effective(now)
                    if eff == "waiting" and not s.muted:
                        s.muted = acted = True
                    elif eff in ("done", "error"):
                        s.set("idle", "", now)
                        acted = True
        return acted

    def snapshot(self):
        now = self.clock()
        agents = {}
        with self.lock:
            for name, sessions in self.agents.items():
                for sid in [k for k, s in sessions.items()
                            if s.effective(now) == "idle" and now - s.last > SESSION_STALE]:
                    del sessions[sid]
                if not sessions:
                    agents[name] = {"state": "offline", "detail": "", "since": None,
                                    "task_start": None, "tools": 0, "sessions": 0,
                                    "cwd": "", "alert": False, "last": None}
                    continue
                best = max(sessions.values(),
                           key=lambda s: (PRIORITY[s.effective(now)], s.last))
                state = best.effective(now)
                agents[name] = {
                    "state": state,
                    "detail": best.detail if state not in ("idle",) else "",
                    "since": round(best.wait_at if state == "waiting" else best.since, 3),
                    "task_start": round(best.task_start, 3) if best.task_start else None,
                    "tools": best.tools,
                    "sessions": len(sessions),
                    "cwd": best.cwd,
                    "alert": state == "waiting" and not best.muted,
                    "last": round(max(s.last for s in sessions.values()), 3),
                }
        focus = max(agents, key=lambda a: (PRIORITY[agents[a]["state"]], agents[a]["last"] or 0),
                    default=None)
        return {"focus": focus, "agents": agents}
