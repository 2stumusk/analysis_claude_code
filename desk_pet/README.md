# Desk Pet：Claude Code / Codex 桌面状态宠物

一个放在桌上的小屏幕宠物：显示 Claude Code 和 Codex 正在做什么、什么时候需要你，空闲时当时钟用，Agent 每完成一个任务它就成长一点。

当前阶段：**电脑端守护进程 + 网页模拟器**（还没有硬件）。模拟器画的就是未来 320×240 屏幕上的内容，读的也是设备将来收到的同一份状态 JSON，硬件到手后只需要写固件把它画出来。

## 快速开始

```bash
cd desk_pet
python3 -m deskpet --demo        # 启动并播放一段演示会话
# 浏览器打开 http://127.0.0.1:7878/
```

需要 Python 3.9+，不用装任何依赖。

### 接入 Claude Code

```bash
python3 -m deskpet hooks claude
```

把输出的 `hooks` 合并进 `~/.claude/settings.json`（或项目里的 `.claude/settings.json`）。

- 大部分事件用 Claude Code 自带的 HTTP hook 直接发给守护进程，不额外起进程，事件顺序也有保证。
- `SessionStart` 只支持 command hook，所以用 `hooks/hook_bridge.py` 转发。
- 守护进程没开时，HTTP hook 会连不上，Claude Code 照常工作；如果你嫌调试日志里有报错，可以把它们都换成 command hook（参考 Codex 的配置）。

### 接入 Codex

```bash
python3 -m deskpet hooks codex
```

把输出写进 `~/.codex/hooks.json`，重启 Codex，在 `/hooks` 里信任这些命令。Codex 全部走 `hook_bridge.py`：它从 stdin 读事件、POST 给守护进程、**不输出任何内容并始终以 0 退出**，不会阻塞或影响 Agent。

旧版 Codex 的 `notify` 也能用：`notify = ["python3", "/绝对路径/hooks/hook_bridge.py", "codex"]`。

## 屏幕

| 按键 | 作用 |
|---|---|
| A | 切换页面：表情 → 时钟 → Agent 列表 → 宠物 |
| B | 有提醒时：确认（停止闪烁 / 清掉 DONE）；没有提醒时：喂食 |

| 状态 | 触发事件 | 表情 |
|---|---|---|
| THINKING | `UserPromptSubmit`、工具调用结束 | 眼睛往右上看 + 省略号 |
| READING | `Read` `Grep` `Glob` `WebFetch` `WebSearch` … | 眼睛左右扫 |
| EDITING | `Edit` `Write` `MultiEdit` `apply_patch` … | 半闭眼盯着看 + 光标 |
| RUNNING | `Bash` `shell` `exec_command` … | 眼睛上下抖 + 转圈 |
| NEEDS YOU | `PermissionRequest`、`Notification`(permission_prompt 等) | 橙色大眼 + 感叹号 + 屏幕边框闪 + LED 闪 |
| DONE | `Stop` | ^ ^ 笑眼 + 星星，45 秒后回到 IDLE |
| ERROR | `StopFailure` | × × + 汗滴 |
| IDLE / OFFLINE | `SessionStart` / 没有会话 | 四处张望 / 闭眼打呼 |

几条规则：

- **多会话、多 Agent**：每个 Agent 显示它最紧急的会话，表情页显示最紧急的那个 Agent（NEEDS YOU > ERROR > 忙碌 > DONE > IDLE）。
- **防误报**：`PermissionRequest` 要过 1.5 秒仍没被处理才提醒，自动批准的请求不会让它闪；`bypassPermissions` 等自动批准模式下直接忽略。
- **宠物养成**：完成任务加经验（基础 10 点，再按工具调用数和耗时加分），每 15 分钟掉 1 点精力，完成任务或按 B 喂食会补回来；精力低时会露出委屈脸。数据存在 `~/.deskpet/pet.json`。
- **今日用量**：从 `~/.claude/projects/**/*.jsonl` 读取本地会话日志，统计 Claude 今天的 token 数，按 `message.id + requestId` 去重。不联网，不读任何凭证。`--no-usage` 可以关掉。

## 隐私与安全

- 只监听 `127.0.0.1`。hook 内容里有你的 prompt 和命令，除非确定局域网可信，不要改成 `--host 0.0.0.0`。
- 屏幕上只显示文件名、截断后的命令（≤48 字符），不保存 prompt。
- 带外站 `Origin` 头的 POST 会被拒绝，防止任意网页伪造状态。
- 账号 token 永远不进设备。

## 状态协议（v1）

`GET /api/state` 返回一个快照，`GET /api/stream` 用 SSE 在状态变化时推送同样的内容。以后的固件通过 Wi-Fi 拉取，或者由守护进程经 BLE / 串口转发。

```json
{
  "v": 1,
  "focus": "claude",
  "agents": {
    "claude": {"state": "running", "detail": "npm test -- cart", "since": 1761480000.1,
               "task_start": 1761479990.0, "tools": 4, "sessions": 1, "cwd": "shop-api",
               "alert": false, "last": 1761480000.1},
    "codex":  {"state": "offline", "...": "..."}
  },
  "pet":   {"level": 2, "xp": 160, "xp_level": 100, "xp_next": 300, "energy": 84,
            "mood": "happy", "tasks_today": 5, "tools_today": 30, "errors_today": 0,
            "levelup_at": null, "fed_at": null},
  "usage": {"claude": {"date": "2026-10-26", "input": 0, "output": 0, "cache_read": 0,
                       "cache_write": 0, "messages": 0}}
}
```

其他接口：`POST /hook/<agent>`（hook 原文，可加 `?event=名字`），`POST /api/button {"button":"B"}`，`POST /api/demo`。

## 目录

```
deskpet/core.py     hook 事件 → 每个 Agent 的显示状态
deskpet/pet.py      经验、等级、精力
deskpet/usage.py    今日 Claude token 统计
deskpet/server.py   HTTP 守护进程 + SSE
deskpet/demo.py     演示脚本（走真实的 hook 处理流程）
hooks/hook_bridge.py  command hook 转发器
web/                网页模拟器（320×240 canvas）
tests/              python3 -m unittest discover -s tests
```

## 下一步

1. 固件：ESP32-S3 + 2 寸屏，用 LVGL 按同一协议画表情、时钟和列表。
2. 用设备按键批准 / 拒绝权限：Claude Code 的 `PermissionRequest` hook 可以返回决定。这个功能涉及安全，要做成显式开启。
3. 兼容 [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy) 的 BLE 协议，让设备也能连 Claude 桌面版。
4. 原创角色和 GIF 皮肤包。
