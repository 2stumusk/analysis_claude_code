"""A scripted session that drives the same hook pipeline as real agents."""

import threading
import time

C = ("claude", "demo-claude")
X = ("codex", "demo-codex")


def _tool(name, **inp):
    return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": inp}


def _ev(name, **extra):
    return dict(hook_event_name=name, **extra)


# (seconds to wait first, (agent, session), payload)
SCRIPT = [
    (0.0, C, _ev("SessionStart", cwd="/work/shop-api")),
    (0.5, X, _ev("SessionStart", cwd="/work/pet-firmware")),
    (1.5, C, _ev("UserPromptSubmit")),
    (2.5, C, _tool("Read", file_path="/work/shop-api/src/cart.ts")),
    (1.5, C, _ev("PostToolUse", tool_name="Read")),
    (0.3, C, _tool("Grep", pattern="applyCoupon")),
    (1.5, X, _ev("UserPromptSubmit")),
    (0.5, C, _tool("Edit", file_path="/work/shop-api/src/cart.ts", old_string="a", new_string="b")),
    (1.0, X, _tool("Bash", command="cargo build --release")),
    (2.5, C, _ev("PostToolUse", tool_name="Edit")),
    (0.3, C, _tool("Bash", command="npm test -- cart")),
    (3.0, C, _ev("PostToolUse", tool_name="Bash")),
    (0.5, C, _ev("PermissionRequest", tool_name="Bash",
                 tool_input={"command": "git push origin feature/coupon"})),
    (2.0, X, _ev("PostToolUse", tool_name="Bash")),
    (0.5, X, _tool("apply_patch", input="*** Begin Patch")),
    (4.0, C, _tool("Bash", command="git push origin feature/coupon")),
    (2.0, C, _ev("PostToolUse", tool_name="Bash")),
    (0.5, C, _ev("Stop")),
    (2.0, X, _ev("PostToolUse", tool_name="apply_patch")),
    (0.5, X, _tool("Bash", command="cargo test")),
    (3.0, X, _ev("StopFailure", error="cargo test: 2 failed")),
    (50.0, C, _ev("SessionEnd")),
    (0.0, X, _ev("SessionEnd")),
]


def run(handle, speed=1.0, stop=None):
    """Feed SCRIPT into `handle(agent, payload)`."""
    for delay, (agent, sid), payload in SCRIPT:
        if stop is not None and stop.wait(delay / speed):
            return
        if stop is None:
            time.sleep(delay / speed)
        handle(agent, dict(payload, session_id=sid))


def start(handle, speed=1.0):
    stop = threading.Event()
    threading.Thread(target=run, args=(handle, speed, stop), daemon=True).start()
    return stop
