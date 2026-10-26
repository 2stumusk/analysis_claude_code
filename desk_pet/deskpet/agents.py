"""Supported agents: display names, identity detection and hook configuration.

Hook formats come from each tool's documentation (see README); only Claude Code
has been exercised end to end so far.
"""

import json
import os
import shlex
import sys

BRIDGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "hooks", "hook_bridge.py")

# id -> (product name, screen label, 2-letter abbreviation, config file, how sure we are)
AGENTS = {
    "claude":   ("Claude Code", "CLAUDE", "CL", "~/.claude/settings.json", "tested"),
    "codex":    ("Codex CLI", "CODEX", "CX", "~/.codex/hooks.json", "community"),
    "gemini":   ("Gemini CLI", "GEMINI", "GM", "~/.gemini/settings.json", "docs"),
    "qwen":     ("Qwen Code", "QWEN", "QW", "~/.qwen/settings.json", "docs"),
    "kimi":     ("Kimi Code", "KIMI", "KM", "~/.kimi-code/config.toml", "docs"),
    "deepseek": ("DeepSeek via Claude Code", "DEEPSEEK", "DS", "~/.claude/settings.json", "docs"),
    "grok":     ("Grok Build", "GROK", "GK", "~/.grok/config.toml", "docs"),
    "muse":     ("Muse Code", "MUSE", "MU", "~/.config/muse/settings.json", "unverified"),
}
ORDER = list(AGENTS)
DEFAULT_AGENTS = ["claude", "codex"]
PRESETS = {
    "duo": ["claude", "codex"],
    "global": ["claude", "codex", "gemini", "grok", "muse"],
    "china": ["kimi", "deepseek", "qwen"],
    "all": ORDER,
}

# Executable names that identify the agent running a hook (process ancestry).
PROCESS_NAMES = {"grok": "grok", "muse": "muse", "kimi": "kimi", "kimi-code": "kimi",
                 "qwen": "qwen", "gemini": "gemini", "codex": "codex", "claude": "claude"}
# Substrings of ANTHROPIC_BASE_URL hosts, for Claude Code pointed at another vendor.
HOST_HINTS = [("deepseek", "deepseek"), ("moonshot", "kimi"), ("kimi", "kimi"),
              ("dashscope", "qwen"), ("aliyuncs", "qwen"), ("x.ai", "grok"),
              ("meta.ai", "muse"), ("llama.com", "muse"), ("googleapis", "gemini")]
MODEL_HINTS = [("deepseek", "deepseek"), ("kimi", "kimi"), ("moonshot", "kimi"),
               ("qwen", "qwen"), ("grok", "grok"), ("muse", "muse"), ("gemini", "gemini")]


def describe(agent_id):
    name, label, abbr, config, status = AGENTS.get(
        agent_id, (agent_id, agent_id.upper()[:8], agent_id.upper()[:2], "", "unknown"))
    return {"id": agent_id, "name": name, "label": label, "abbr": abbr,
            "config": config, "status": status}


def normalize_list(agents):
    """Known ids only, in registry order, without duplicates."""
    wanted = set(agents or [])
    return [a for a in ORDER if a in wanted]


def identify(endpoint, payload, hints):
    """Return the agent that really produced a hook payload.

    `hints` is what hook_bridge.py could see from inside the hook process."""
    hints = hints if isinstance(hints, dict) else {}
    forced = hints.get("as")
    if forced in AGENTS:
        return forced
    for proc in hints.get("procs") or []:
        found = PROCESS_NAMES.get(str(proc).lower())
        if found:
            # A "claude" ancestor only confirms Claude; vendor checks still apply.
            if found != "claude":
                return found
            break
    host = str(hints.get("base_url_host") or "").lower()
    for needle, agent in HOST_HINTS:
        if needle in host:
            return agent
    model = str(payload.get("model") or hints.get("model") or "").lower()
    if endpoint == "claude":
        for needle, agent in MODEL_HINTS:
            if needle in model:
                return agent
    return None


# ---------- hook configuration ----------

CLAUDE_STYLE_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                       "PostToolUseFailure", "PermissionRequest", "Notification",
                       "SubagentStart", "SubagentStop", "PreCompact", "Stop",
                       "StopFailure", "SessionEnd"]
CODEX_EVENTS = ["SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
                "PostToolUse", "PermissionRequest", "SubagentStart", "SubagentStop",
                "PreCompact", "PostCompact", "Stop", "Interrupt"]
GEMINI_EVENTS = ["SessionStart", "SessionEnd", "BeforeAgent", "AfterAgent", "BeforeTool",
                 "AfterTool", "Notification", "PreCompress"]
KIMI_EVENTS = ["SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "PostToolUseFailure", "PermissionRequest", "PermissionResult", "SubagentStart",
               "SubagentStop", "PreCompact", "PostCompact", "Notification", "Stop",
               "StopFailure", "Interrupt"]
GROK_NOTIFY_EVENTS = ["session_ready", "approval_required", "turn_complete", "agent_error"]
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
               "BeforeTool", "AfterTool"}


def bridge_command(agent, port, *extra):
    parts = [sys.executable or "python3", BRIDGE, agent, *extra]
    if port != 7878:
        parts += ["--port", str(port)]
    if os.name == "nt":
        return " ".join('"%s"' % p if " " in p else p for p in parts)
    return " ".join(shlex.quote(p) for p in parts)


def _json_hooks(events, command, timeout):
    hooks = {}
    for ev in events:
        entry = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if ev in TOOL_EVENTS:
            entry = {"matcher": "*", **entry}
        hooks[ev] = [entry]
    return hooks


def _toml_str(s):
    return json.dumps(s)  # JSON string escapes are valid TOML basic strings


def hook_config(agent, port=7878):
    """Return (file to edit, config text, notes) for one agent."""
    if agent in ("claude", "deepseek"):
        # Every event goes through the bridge so it can tell real Claude apart
        # from DeepSeek/Kimi/Qwen backends and from Grok, which runs these hooks too.
        cfg = {"hooks": _json_hooks(CLAUDE_STYLE_EVENTS, bridge_command("claude", port), 5)}
        notes = []
        if agent == "deepseek":
            notes.append("DeepSeek 没有自己的 CLI：按 DeepSeek 官方文档把 Claude Code 的 "
                         "ANTHROPIC_BASE_URL 设为 https://api.deepseek.com/anthropic，"
                         "装上这份 Claude Code hooks，deskpet 会按 API 地址自动识别成 DEEPSEEK。")
            notes.append("走自建代理/路由时识别不到，可在 command 末尾加 `--as deepseek` 强制指定。")
        return "~/.claude/settings.json", json.dumps(cfg, indent=2), notes
    if agent == "codex":
        cfg = {"hooks": _json_hooks(CODEX_EVENTS, bridge_command("codex", port), 5)}
        return "~/.codex/hooks.json", json.dumps(cfg, indent=2), [
            "重启 Codex 后在 /hooks 里信任这些命令。"]
    if agent == "gemini":
        cfg = {"hooks": _json_hooks(GEMINI_EVENTS, bridge_command("gemini", port), 5000)}
        return "~/.gemini/settings.json", json.dumps(cfg, indent=2), [
            "Gemini CLI 的 timeout 单位是毫秒。",
            "旧版本需要先开启 hooks，各资料说法不一，以 /hooks 命令或官方文档为准。"]
    if agent == "qwen":
        cfg = {"hooks": _json_hooks(CLAUDE_STYLE_EVENTS, bridge_command("qwen", port), 5)}
        return "~/.qwen/settings.json", json.dumps(cfg, indent=2), []
    if agent == "kimi":
        cmd = bridge_command("kimi", port)
        blocks = ["[[hooks]]\nevent = %s\ncommand = %s\ntimeout = 5\n" % (_toml_str(ev), _toml_str(cmd))
                  for ev in KIMI_EVENTS]
        return "~/.kimi-code/config.toml", "\n".join(blocks), [
            "[[hooks]] 只允许 event / matcher / command / timeout 四个字段，多写会导致配置加载失败。"]
    if agent == "grok":
        text = ("[[ui.notifications.hooks]]\ncommand = %s\nevents = [%s]\n"
                "only_unfocused = false\ntimeout_secs = 5\n") % (
            _toml_str(bridge_command("grok", port, "--grok-env")),
            ", ".join(_toml_str(e) for e in GROK_NOTIFY_EVENTS))
        return "~/.grok/config.toml", text, [
            "这是 Grok 的通知 hooks，只有就绪 / 等你批准 / 完成 / 出错四种状态。",
            "Grok 还会执行 ~/.claude/settings.json 里的 hooks：装了 Claude Code 的 hooks 后，"
            "deskpet 会按进程自动把它们归到 GROK，可以看到读文件、跑命令等细节。"]
    if agent == "muse":
        cfg = {"schema_version": 1,
               "hooks": _json_hooks(CLAUDE_STYLE_EVENTS + ["PostToolBatch"], bridge_command("muse", port), 5)}
        return "~/.config/muse/settings.json", json.dumps(cfg, indent=2), [
            "未核实：Muse Code 的 hooks 格式只查到第三方资料，事件名与 Claude Code 一致，"
            "配置结构请以 dev.meta.ai 官方文档为准。"]
    raise ValueError("unknown agent: %s" % agent)
