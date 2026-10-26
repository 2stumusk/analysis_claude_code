"""A scripted session that drives the same hook pipeline as real agents.

The first two agents on screen play the main script; any others run a short
read-edit-test loop each, staggered so the screen has something to show."""

import threading


def _tool(name, **inp):
    return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": inp}


def _ev(name, **extra):
    return dict(hook_event_name=name, **extra)


# (seconds since start, role, payload); role A and B are the first two agents.
MAIN = [
    (0.0, "A", _ev("SessionStart", cwd="/work/shop-api")),
    (0.5, "B", _ev("SessionStart", cwd="/work/pet-firmware")),
    (2.0, "A", _ev("UserPromptSubmit")),
    (4.5, "A", _tool("Read", file_path="/work/shop-api/src/cart.ts")),
    (6.0, "A", _ev("PostToolUse", tool_name="Read")),
    (6.3, "A", _tool("Grep", pattern="applyCoupon")),
    (7.8, "B", _ev("UserPromptSubmit")),
    (8.3, "A", _tool("Edit", file_path="/work/shop-api/src/cart.ts", old_string="a", new_string="b")),
    (9.3, "B", _tool("Bash", command="cargo build --release")),
    (11.8, "A", _ev("PostToolUse", tool_name="Edit")),
    (12.1, "A", _tool("Bash", command="npm test -- cart")),
    (15.1, "A", _ev("PostToolUse", tool_name="Bash")),
    (15.6, "A", _ev("PermissionRequest", tool_name="Bash",
                    tool_input={"command": "git push origin feature/coupon"})),
    (17.6, "B", _ev("PostToolUse", tool_name="Bash")),
    (18.1, "B", _tool("apply_patch", input="*** Begin Patch")),
    (22.1, "A", _tool("Bash", command="git push origin feature/coupon")),
    (24.1, "A", _ev("PostToolUse", tool_name="Bash")),
    (24.6, "A", _ev("Stop")),
    (26.6, "B", _ev("PostToolUse", tool_name="apply_patch")),
    (27.1, "B", _tool("Bash", command="cargo test")),
    (30.1, "B", _ev("StopFailure", error="cargo test: 2 failed")),
    (80.0, "A", _ev("SessionEnd")),
    (80.0, "B", _ev("SessionEnd")),
]

EXTRA = [
    (0.0, _ev("SessionStart", cwd="/work/docs-site")),
    (1.0, _ev("UserPromptSubmit")),
    (2.5, _tool("Read", file_path="/work/docs-site/README.md")),
    (5.0, _tool("Edit", file_path="/work/docs-site/guide.md", old_string="a", new_string="b")),
    (8.0, _tool("Bash", command="npm run build")),
    (12.0, _ev("Stop")),
    (70.0, _ev("SessionEnd")),
]


def timeline(cast):
    """Merge the scripts for `cast` (list of agent ids) into one sorted timeline."""
    if not cast:
        return []
    roles = {"A": cast[0], "B": cast[1] if len(cast) > 1 else None}
    out = [(t, roles[r], p) for t, r, p in MAIN if roles[r]]
    for i, agent in enumerate(cast[2:]):
        start = 3.0 + i * 2.5
        out += [(start + t, agent, p) for t, p in EXTRA]
    out.sort(key=lambda x: x[0])
    return out


def run(handle, cast, speed=1.0, stop=None):
    """Feed the timeline into `handle(agent, payload)`."""
    stop = stop or threading.Event()
    elapsed = 0.0
    for at, agent, payload in timeline(cast):
        if stop.wait((at - elapsed) / speed):
            return
        elapsed = at
        handle(agent, dict(payload, session_id="demo-" + agent))


def start(handle, cast, speed=1.0):
    stop = threading.Event()
    threading.Thread(target=run, args=(handle, cast, speed, stop), daemon=True).start()
    return stop
