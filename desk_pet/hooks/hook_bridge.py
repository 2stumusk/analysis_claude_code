#!/usr/bin/env python3
"""Forward one agent hook payload to the deskpet daemon.

Command hook:        hook_bridge.py <agent> [--as <agent>] [--port N]   (payload on stdin)
Codex notify:        hook_bridge.py codex '<json>'                      (payload as argument)
Grok notifications:  hook_bridge.py grok --grok-env                     (payload in $GROK_*)

Besides the payload it sends a few hints so the daemon can tell who really ran
the hook: the names of the parent processes (Grok also runs Claude Code's
hooks), the host of ANTHROPIC_BASE_URL and ANTHROPIC_MODEL (Claude Code pointed
at DeepSeek, Kimi or Qwen). No keys, tokens or full URLs are sent.

It always exits 0 and prints nothing, with one exception: a PermissionRequest
from Claude Code or Codex waits (up to the daemon's approval time) in case the
desk pet's buttons decide it, and then prints only the fixed allow/deny output
built here, never text from the daemon. Hook stdout may be read by the agent.
"""

import json
import os
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse

INTERPRETERS = {"node", "bun", "deno", "python", "python3", "npx"}
# Endpoints whose PermissionRequest hooks can be answered from the device.
WAITERS = {"claude", "codex"}
WAIT_TIMEOUT = 75  # the daemon holds a request for at most 60 s
DENY_MESSAGE = "Denied from the deskpet device."
GROK_EVENTS = {
    "session_ready": {"hook_event_name": "SessionStart"},
    "approval_required": {"hook_event_name": "Notification", "notification_type": "permission_prompt"},
    "turn_complete": {"hook_event_name": "Stop"},
    "agent_error": {"hook_event_name": "StopFailure"},
}


def _name(args):
    """Program name from an argv list, looking past interpreters like node."""
    names = [os.path.basename(a).lower() for a in args[:2] if a]
    if len(names) > 1 and names[0] in INTERPRETERS and not names[1].startswith("-"):
        return os.path.splitext(names[1])[0]
    return os.path.splitext(names[0])[0] if names else ""


def parent_names(depth=5):
    names = []
    pid = os.getppid()
    if os.path.isdir("/proc"):
        for _ in range(depth):
            try:
                with open("/proc/%d/cmdline" % pid, "rb") as f:
                    names.append(_name(f.read().decode(errors="replace").split("\0")))
                with open("/proc/%d/stat" % pid) as f:
                    pid = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                break
            if pid <= 1:
                break
        return names
    if os.name == "nt":
        return names
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], capture_output=True,
                         text=True, timeout=1).stdout
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2].split())
    for _ in range(depth):
        if pid not in table:
            break
        ppid, args = table[pid]
        names.append(_name(args))
        pid = ppid
    return names


def hints(forced):
    h = {}
    if forced:
        h["as"] = forced
    try:
        h["procs"] = parent_names()
    except Exception:  # noqa: BLE001 - hints are best effort
        pass
    host = urlparse(os.environ.get("ANTHROPIC_BASE_URL", "")).hostname
    if host:
        h["base_url_host"] = host
    if os.environ.get("ANTHROPIC_MODEL"):
        h["model"] = os.environ["ANTHROPIC_MODEL"][:80]
    return h


def hook_output(decision):
    """PermissionRequest decision output, in the format both Claude Code and
    Codex document; None unless decision is exactly 'allow' or 'deny'."""
    if decision not in ("allow", "deny"):
        return None
    out = {"behavior": decision}
    if decision == "deny":
        out["message"] = DENY_MESSAGE
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": out}}


def main(argv):
    if len(argv) < 2:
        return
    agent, rest = argv[1], argv[2:]
    port = os.environ.get("DESKPET_PORT", "7878")
    forced, grok_env, positional = None, False, []
    while rest:
        arg = rest.pop(0)
        if arg == "--port" and rest:
            port = rest.pop(0)
        elif arg == "--as" and rest:
            forced = rest.pop(0)
        elif arg == "--grok-env":
            grok_env = True
        else:
            positional.append(arg)

    if grok_env:
        event = os.environ.get("GROK_EVENT", "")
        if event not in GROK_EVENTS:
            return
        payload = dict(GROK_EVENTS[event], session_id=os.environ.get("GROK_SESSION_ID", ""),
                       message=os.environ.get("GROK_MESSAGE", "")[:200])
    else:
        if positional:  # Codex notify passes the event JSON as the last argument
            raw = positional[-1].encode()
        elif not sys.stdin.isatty():
            raw = sys.stdin.buffer.read(2 * 1024 * 1024)
        else:
            return
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
    payload["_deskpet"] = hints(forced)
    wait = agent in WAITERS and payload.get("hook_event_name") == "PermissionRequest"

    req = urllib.request.Request(
        "http://127.0.0.1:%s/hook/%s%s" % (port, agent, "?wait=1" if wait else ""),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # The daemon is local; never let a proxy setting route prompts elsewhere.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    body = opener.open(req, timeout=WAIT_TIMEOUT if wait else 1.0).read()
    if wait:
        reply = json.loads(body or b"{}")
        out = hook_output(reply.get("decision") if isinstance(reply, dict) else None)
        if out:
            sys.stdout.write(json.dumps(out))
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception:  # noqa: BLE001 - the agent must never see a failure
        pass
    sys.exit(0)
