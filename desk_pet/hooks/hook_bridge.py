#!/usr/bin/env python3
"""Forward one agent hook payload to the deskpet daemon.

Used as a command hook:   hook_bridge.py <agent> [--port N]       (payload on stdin)
or as Codex `notify`:     hook_bridge.py codex '<json>'          (payload as argument)

It prints nothing and always exits 0, so it can never block or steer the agent:
hook stdout may be read by the agent as instructions.
"""

import json
import os
import sys
import urllib.request


def main(argv):
    if len(argv) < 2:
        return
    agent, rest = argv[1], argv[2:]
    port = os.environ.get("DESKPET_PORT", "7878")
    if len(rest) >= 2 and rest[0] == "--port":
        port, rest = rest[1], rest[2:]

    if rest:  # Codex notify passes the event JSON as the last argument
        raw = rest[-1].encode()
    elif not sys.stdin.isatty():
        raw = sys.stdin.buffer.read(2 * 1024 * 1024)
    else:
        return
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return

    req = urllib.request.Request(
        "http://127.0.0.1:%s/hook/%s" % (port, agent),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # The daemon is local; never let a proxy setting route prompts elsewhere.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.open(req, timeout=1.0).read()


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception:  # noqa: BLE001 - the agent must never see a failure
        pass
    sys.exit(0)
