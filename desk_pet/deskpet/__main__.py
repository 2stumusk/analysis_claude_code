"""deskpet command line.

  python -m deskpet                 start the daemon and web simulator
  python -m deskpet --demo          same, and play a demo session
  python -m deskpet hooks claude    print hook config for ~/.claude/settings.json
  python -m deskpet hooks codex     print hook config for ~/.codex/hooks.json
"""

import argparse
import json
import os
import shlex
import sys

from .server import serve

BRIDGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "hooks", "hook_bridge.py")
CLAUDE_EVENTS = ["UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
                 "PermissionRequest", "Notification", "SubagentStart", "SubagentStop",
                 "PreCompact", "Stop", "StopFailure", "SessionEnd"]
CODEX_EVENTS = ["SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
                "PostToolUse", "PermissionRequest", "SubagentStart", "SubagentStop",
                "PreCompact", "PostCompact", "Stop", "Interrupt"]
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}


def bridge_command(agent, port):
    parts = [sys.executable or "python3", BRIDGE, agent]
    if port != 7878:
        parts += ["--port", str(port)]
    if os.name == "nt":
        return " ".join('"%s"' % p if " " in p else p for p in parts)
    return " ".join(shlex.quote(p) for p in parts)


def _entry(event, hook):
    entry = {"hooks": [hook]}
    if event in TOOL_EVENTS:
        entry = {"matcher": "*", **entry}
    return entry


def hooks_config(agent, port):
    url = "http://127.0.0.1:%d/hook/%s" % (port, agent)
    command = {"type": "command", "command": bridge_command(agent, port), "timeout": 5}
    if agent == "claude":
        # HTTP hooks keep event order and need no extra process; SessionStart
        # only accepts command hooks.
        hooks = {"SessionStart": [_entry("SessionStart", command)]}
        for ev in CLAUDE_EVENTS:
            hooks[ev] = [_entry(ev, {"type": "http", "url": url, "timeout": 3})]
        return {"hooks": hooks}
    return {"hooks": {ev: [_entry(ev, command)] for ev in CODEX_EVENTS}}


def main(argv=None):
    p = argparse.ArgumentParser(prog="deskpet", description="Desk pet for coding agents")
    sub = p.add_subparsers(dest="cmd")
    h = sub.add_parser("hooks", help="print hook configuration")
    h.add_argument("agent", choices=["claude", "codex"])
    h.add_argument("--port", type=int, default=7878)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1; hook payloads contain your prompts)")
    p.add_argument("--port", type=int, default=7878)
    p.add_argument("--demo", action="store_true", help="play a demo session on start")
    p.add_argument("--no-usage", action="store_true", help="do not read ~/.claude/projects")
    p.add_argument("--state-file", default=os.path.join(os.path.expanduser("~"), ".deskpet", "pet.json"))
    args = p.parse_args(argv)

    if args.cmd == "hooks":
        print(json.dumps(hooks_config(args.agent, args.port), indent=2))
        return 0

    app, httpd = serve(args.host, args.port, args.state_file,
                       usage=not args.no_usage, demo_on_start=args.demo)
    print("deskpet: simulator at http://%s:%d/" % (
        "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host, args.port))
    print("         hook config: python -m deskpet hooks claude | codex")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
