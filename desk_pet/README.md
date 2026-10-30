# Desk Pet：AI 编程 Agent 桌面状态宠物

一个放在桌上的小屏幕宠物：显示 Claude Code、Codex、Gemini、Qwen、Kimi、DeepSeek、Grok、Muse 这些 Agent 正在做什么、什么时候需要你，空闲时当时钟用，Agent 每完成一个任务它就成长一点。

当前阶段：**电脑端守护进程 + 网页模拟器 + ESP32 固件**。固件支持 M5Stack Basic / Core2 和 CYD 三种板子，都已编译通过；M5Stack Basic 已在真机上跑通，Core2 和 CYD 还没实测，详见 [firmware/README.md](firmware/README.md)。板子通过 USB 串口连接：`python3 -m deskpet --serial auto`。

## 快速开始

```bash
git clone https://github.com/2stumusk/desk-pet.git
cd desk-pet
python3 -m deskpet --demo                    # 启动并播放一段演示会话
python3 -m deskpet --agents china --demo     # 只显示国产三家
python3 -m deskpet --city 无锡                # 打开天气页（城市会记住）
# 浏览器打开 http://127.0.0.1:7878/
```

需要 Python 3.9+，不用装任何依赖。

## 支持的 Agent

```bash
python3 -m deskpet agents           # 列表
python3 -m deskpet hooks <agent>    # 输出这个 Agent 的 hooks 配置（stderr 里有写到哪个文件、注意事项）
```

| id | 产品 | 配置写到 | 接法 | 可信度 |
|---|---|---|---|---|
| `claude` | Claude Code | `~/.claude/settings.json` | 全部生命周期 hooks | **已实测**（Claude Code 2.1.310；Mac + M5Stack 真机） |
| `codex` | Codex CLI | `~/.codex/hooks.json` | 全部生命周期 hooks；重启后要在 `/hooks` 里信任，否则会被静默跳过 | **已实测**（Mac + M5Stack 真机） |
| `gemini` | Gemini CLI | `~/.gemini/settings.json` | `BeforeTool` `AfterAgent` 等 Gemini 自己的事件名，timeout 单位是毫秒 | 按官方文档 |
| `qwen` | Qwen Code | `~/.qwen/settings.json` | 与 Claude Code 同名的事件，工具名是 `run_shell_command` 这类 | 按官方文档 |
| `kimi` | Kimi Code | `~/.kimi-code/config.toml` | TOML `[[hooks]]`，只允许 event / matcher / command / timeout | 按官方文档 |
| `deepseek` | DeepSeek（经 Claude Code） | `~/.claude/settings.json` | 用 Claude Code 接 DeepSeek 的 Anthropic 兼容接口时，deskpet 按 API 地址自动识别 | 按官方文档 |
| `dsh` | DeepSeek Harness | dsh 的 profile | DeepSeek 官方开源的编程 Agent（命令行 `dsh`）。它没有 hooks 文件，所以用 Cordis 插件 `integrations/dsh` 监听会话事件；`python3 -m deskpet hooks dsh` 输出安装命令 | 按官方文档和源码（插件已用 Node 模拟事件测过，未在真实 dsh 里跑） |
| `grok` | Grok Build | `~/.grok/config.toml` | 通知 hooks（就绪 / 待批准 / 完成 / 出错）；Grok 还会执行 `~/.claude/settings.json` 里的 hooks，deskpet 按进程自动识别 | 按官方文档 |
| `muse` | Muse Code | `~/.config/muse/settings.json` | 事件名与 Claude Code 一致 | **未核实**：只查到第三方资料 |

"按官方文档"表示格式来自官方文档或官方仓库里的文档，但还没在真实环境里跑过。不同版本的字段可能有变化，装上后看一眼 Agent 自己的 `/hooks` 命令是否已加载。

### 可选模式

网页右侧的"显示哪些 Agent"，或者启动参数 `--agents`：

- **自选**：勾选要显示的 Agent。预设有 `duo`（Claude + Codex，默认）、`global`（海外）、`china`（Kimi、DeepSeek、DeepSeek Harness、Qwen）、`all`（全部 9 个；设备屏幕最多显示前 8 个）。也可以写成 `--agents claude,kimi,deepseek`。
- **自动**：哪个 Agent 有活动会话就显示哪个。
- 选择会保存在 `~/.deskpet/config.json`。没显示的 Agent 照样在后台记录状态，切换后立即可见。
- 屏幕自动适配数量：超过 2 个时，顶栏改用缩写（CL CX GM QW KM DS DH GK MU）；超过 3 个时，时钟页改为两列小标签，Agent 页改为紧凑行（每个 Agent 一行）。

### 自动识别"到底是谁"

同一个 Claude Code 可以接 DeepSeek、Kimi、Qwen 的接口，Grok 也会执行 Claude Code 的 hooks。为了区分它们，所有 hook 都经过 `hooks/hook_bridge.py`，它会附带几条线索：

1. **父进程名**：调用链上先出现 `grok` / `muse` / `kimi` / `qwen` / `gemini` / `codex`，就归给那个 Agent；先出现 `claude`，就确认是 Claude Code。
2. **`ANTHROPIC_BASE_URL` 的主机名**：`deepseek` → DEEPSEEK，`moonshot` / `kimi` → KIMI，`dashscope` / `aliyuncs` → QWEN，等等。
3. **模型名**：`ANTHROPIC_MODEL` 或事件里的 `model` 字段。
4. **兜底**：走自建代理或路由时识别不到，在 command 末尾加 `--as deepseek` 强制指定。

只发送主机名和模型名，**不发送 key、token 或完整 URL**。同一会话识别过一次后会记住，后续事件即使不带线索也会归到同一个 Agent。

## 屏幕

| 按键 | 作用 |
|---|---|
| A | 切换页面：表情 → 时钟 → 天气 → Agent 列表 → 宠物（只在勾选的页面之间切换） |
| B | 确认表情页上**这一个** Agent 的提醒（停止闪烁 / 清掉 DONE），画面会跳到下一个在等你的 Agent；它没什么可确认时就喂食 |
| 长按 B | 一次确认**所有** Agent（网页上也可以按 Shift+B） |
| C | 声音开关 |

权限请求出现在屏幕上时（要先打开，见下面"按键批准权限"），三个键临时变成 **A 拒绝 / B 允许 / C 交给电脑**。

| 状态 | 触发事件（各家同义事件已统一） | 表情 |
|---|---|---|
| THINKING | `UserPromptSubmit` / `BeforeAgent`、工具调用结束 | 眼睛往右上看 + 省略号 |
| READING | `Read` `Grep` `read_file` `ReadFile` `web_fetch` … | 眼睛左右扫 |
| EDITING | `Edit` `Write` `apply_patch` `replace` `StrReplaceFile` … | 半闭眼盯着看 + 光标 |
| RUNNING | `Bash` `shell` `run_shell_command` `Shell` `exec_command` … | 眼睛上下抖 + 转圈 |
| NEEDS YOU | `PermissionRequest`、权限类 `Notification`（Gemini 的 `ToolPermission` 等） | 橙色大眼 + 感叹号 + 屏幕边框闪 + LED 闪 |
| DONE | `Stop` / `AfterAgent` | ^ ^ 笑眼 + 星星，45 秒后回到 IDLE |
| ERROR | `StopFailure` | × × + 汗滴 |
| IDLE / OFFLINE | `SessionStart` / 没有会话 | 四处张望 / 闭眼打呼 |

几条规则：

- **多会话、多 Agent**：每个 Agent 显示它最紧急的会话，表情页显示最紧急的那个 Agent，详见下一节。
- **防误报**：`PermissionRequest` 要过 1.5 秒仍没被处理才提醒，自动批准的请求不会让它闪。3 秒内重复的 `Stop` 只算一次，所以 Grok 的通知 hooks 和 Claude 格式 hooks 同时装也不会重复加经验。
- **宠物养成**：完成任务加经验（基础 10 点，再按工具调用数和耗时加分），每 15 分钟掉 1 点精力，完成任务或按 B 喂食会补回来；精力低时会露出委屈脸。数据存在 `~/.deskpet/pet.json`。
- **今日用量**：从 `~/.claude/projects/**/*.jsonl` 统计 Claude Code 今天的 token 数，按 `message.id + requestId` 去重。不联网，不读凭证。`--no-usage` 可以关掉。其他 Agent 暂不统计用量。

## 多个 Agent 同时工作

- **表情页显示谁**：未确认的提醒优先，然后按 NEEDS YOU > ERROR > 忙碌 > DONE > IDLE 排序。
  - 同级时显示最近有动作的那个。
- **轮流显示**：两个以上的 Agent 同时在忙、又没人需要你时，表情页每 6 秒换一个，Agent 名旁边显示 `2/3` 这样的进度。
  - 有 Agent 需要你或出错时立刻停止轮换。
  - 可以在网页"显示哪些 Agent"里关掉，设置记在 `config.json` 的 `rotate`。
- **单独确认**：短按 B 只确认屏幕上这一个；Agent 列表页用小三角标出它是哪一个。
  - 设备会把 Agent 名一起发给电脑，所以确认的就是你看到的那个，不会因为刚好轮换而确认错。
- **其他 Agent**：顶栏每个一个彩色圆点，需要你时会闪；按 A 切到列表页可以同时看到全部。

## 按键批准权限

Claude Code 或 Codex 要你批准一个操作（跑命令、改文件……）时，可以直接在桌宠上按键决定。

- **默认关闭**：在网页"按键批准权限"里勾选才生效，设置记在 `config.json` 的 `approvals`。只在桌宠 USB 连着、或模拟器网页开着时起作用。
- **屏幕显示**：哪个 Agent、什么工具、具体命令或文件（最多 120 字符），以及倒计时。
- **按键**：A 拒绝，B 允许，C 交给电脑。触屏板（CYD）是左半边拒绝、右半边允许、长按任意处交给电脑。
  - 请求刚出现的 0.8 秒内按键无效，防止你正好在按别的键时误批。
  - 长按任何键都不会"允许"。
- **退回电脑**：限时内（默认 30 秒，可选 10–60 秒）没按、按了 C、设备拔掉、或者你在电脑上已经处理了，都会把请求还给 Agent，电脑上照常弹出确认框。
- **不会批错**：设备回传请求编号，守护进程只接受正在等待的那一个；编号每次启动都不同。
- **范围**：只对 Claude Code（包括接 DeepSeek / Kimi / 千问 API 的 Claude Code）和 Codex 生效，这两家的返回格式查过官方文档 / 源码。Grok、Gemini、Kimi Code 等仍然只提醒、不代批。
- **规则仍然有效**：按"允许"后，你在 Claude Code 里配的 deny 规则照样生效（官方文档说明）。

打开前需要**更新 hooks 配置**：`PermissionRequest` 的超时从 5 秒改成了 90 秒，否则 Agent 等不到按键。用 `python3 -m deskpet hooks claude`（或 `codex`）重新生成并替换；Codex 改完要重启并在 `/hooks` 里重新信任。

工作方式：`hook_bridge.py` 收到 `PermissionRequest` 后带 `?wait=1` 请求守护进程并等待，拿到决定后输出：

```json
{"hookSpecificOutput": {"hookEventName": "PermissionRequest",
  "decision": {"behavior": "deny", "message": "Denied from the deskpet device."}}}
```

- 这个格式同时符合 Claude Code hooks 文档的 "PermissionRequest decision control"，以及 Codex 源码里的输出 schema（`codex-rs/hooks/schema/generated/permission-request.command.output.schema.json`）。
- 不发送 `interrupt`、`updatedInput`、`updatedPermissions`：Codex 遇到这几个字段会按拒绝处理。
- 输出由 bridge 自己拼，不转发守护进程的文字。没有决定时什么都不输出。

还没在真机上验证的一点：Claude Code 文档没写 hook 执行期间电脑上的确认框是否同时出现。如果同时出现，你在电脑上点了，桌宠上的请求也会自动消失（Agent 的下一个事件会释放它）。

## 表情风格：像素猫

表情页默认是一只原创的像素小猫：白毛、橘色花斑，32×32 像素放大 4 倍显示。在网页"表情风格"里可以换回原来的"大眼睛"，设置记在 `config.json` 的 `skin`（`cat` 或 `eyes`）。

| 状态 | 小猫在做什么 |
|---|---|
| 思考中 | 眼睛往上看，眨眼，头顶冒省略号 |
| 读文件 | 捧着一本书，眼睛左右看 |
| 改代码 / 跑命令 | 在笔记本上敲键盘（跑命令时敲得更快，旁边转圈） |
| 需要你 | 睁大眼睛举爪招手，旁边一个"!" |
| 完成啦 | 眯眼笑，周围闪星星 |
| 出错了 | × × 眼，炸毛，冒汗 |
| 空闲 / 饿了 | 坐着甩尾巴、偶尔眨眼 / 垂头丧气 |
| 离线 | 闭眼打盹，飘 z |

下方信息卡显示：Agent 名、中文状态、正在做的事，以及**用时**和**工具调用次数**。

- 进度条只表示"正在忙"：一段色块来回扫，完成或出错时填满，需要你时闪烁。
- 它**不是**完成百分比。hooks 只告诉我们开始、用了什么工具、结束，没有"完成了百分之几"的数据，所以不显示百分比。

小猫是用 `firmware/tools/cat_art.py` 里的几何形状加自动描边画出来的。原创形象，没有用任何现成角色或别人的素材。这个脚本同时生成固件的 `src/cat_art.h` 和网页的 `web/cat_art.js`，两边像素完全一致；有测试保证两份生成文件和脚本同步。

## 中文显示

命令、文件名、项目目录里的中文会在设备上正常显示，不再变成 `?`。

- **字体**：LovyanGFX 自带的 efontCN_12，12 像素点阵字体，BSD 许可。它覆盖 GB2312 的全部 6763 个汉字和常用中文标点，固件因此大了约 216 KB（M5Stack Basic 的程序区用到 1.3 MB 里的 691 KB）。
- **显示规则**：一段文字里只要有非英文字符，整段就换成这个字体显示。英文字母占 6 像素宽，汉字占 12 像素宽。
- **不支持的字**：GB2312 以外的字（生僻字、繁体专用字、emoji、日文假名等）由电脑端先换成 `?`。
- **长度**：电脑端按"汉字算 2 格"截断，状态行最多 48 格，权限请求最多 120 格。串口上直接发 UTF-8，一个汉字占 3 字节。
- **网页模拟器**：用浏览器字体，本来就能显示中文。

## 夜间息屏

在网页"夜间息屏"里打开，设定时间段（默认 23:00–07:00，可以跨午夜），选择"熄屏"或"调暗"。设置记在 `config.json` 的 `night`。

- **时间**：按电脑的本地时间算，守护进程每帧把当前状态告诉设备。
- **照样亮屏**：有 Agent 需要你，或有权限请求等你按键时，屏幕会亮起来；处理完再回到熄屏 / 调暗。
- **按键**：夜间按任意键，屏幕亮 30 秒。屏幕全黑时，这一下只负责点亮，不会触发切页、确认或批准。
- **声音**：夜里只有"需要你"会响，任务完成和出错的提示音静音。CYD 的指示灯同样只在需要你时亮。
- 熄屏时设备不再绘制画面，但仍然收发状态，所以一亮屏就是最新内容。

## 页面与天气

- **选页面**：在网页"页面与天气"里勾选，或用 `--pages face,clock,weather`。A 键只在勾选的页面之间切换，至少保留一页。
- **天气**：在网页里输入城市保存，或用 `--city 无锡`，会记在 `~/.deskpet/config.json`。
  - 守护进程每 20 分钟查一次；失败时 5 分钟后重试，期间继续显示上一次的数据，超过 1 小时会标"过期"。
  - 天气页显示：当前温度、天气、最高最低温、体感、湿度、风速、降水概率，以及接下来 12 小时（每 2 小时一格）。时钟页也会多一行天气摘要。
  - 城市名和天气描述用英文显示（无锡 → Wuxi），英文名由地理编码接口返回。
  - 中文名查不到时会自动补“市”再查一次（Open-Meteo 对两个字的查询只做精确匹配）；还查不到就改用英文或拼音（`--city Wuxi`），或直接填坐标 `--city 31.49,120.31`。
- **数据来源**：[Open-Meteo](https://open-meteo.com)，不用注册，但官方条款写明**免费接口仅限非商业用途**（[条款](https://open-meteo.com/en/terms)），产品商用前要换付费套餐或别的数据源。
  - 换数据源只需在 `deskpet/weather.py` 写一个带 `locate()` 和 `fetch(place)` 的类，其余代码不用动。
  - 会发出的数据：城市名（用于查坐标），以及坐标（用于查天气）。

## 隐私与安全

- 只监听 `127.0.0.1`。hook 内容里有你的 prompt 和命令，除非确定局域网可信，不要改成 `--host 0.0.0.0`。
- 屏幕上只显示文件名、截断后的命令（≤48 格；权限请求页 ≤120 格，汉字算 2 格），不保存 prompt。
- 带外站 `Origin` 头的 POST 会被拒绝，防止任意网页伪造状态。
- `hook_bridge.py` 始终以 0 退出。唯一会输出内容的情况：你打开了"按键批准权限"，并且在设备上按了允许或拒绝。这时它输出上面那段固定格式的 JSON。其余情况都不输出，也不等待。

## 状态协议（v1）

`night` 是夜间状态：0 正常，1 调暗，2 熄屏。

`approval` 在有权限请求等按键时是 `{"id", "agent", "label", "tool", "detail", "deadline", "wait"}`，否则为 `null`。

`GET /api/state` 返回一个快照，`GET /api/stream` 用 SSE 在状态变化时推送同样的内容。`order` 是屏幕要显示的 Agent 顺序，`label` 和 `abbr` 由守护进程给出，以后新增 Agent 不用改固件。

```json
{
  "v": 1,
  "mode": "custom",
  "order": ["claude", "deepseek"],
  "focus": "deepseek",
  "agents": {
    "claude":   {"state": "idle", "label": "CLAUDE", "abbr": "CL", "...": "..."},
    "deepseek": {"state": "running", "label": "DEEPSEEK", "abbr": "DS",
                 "detail": "npm test -- cart", "since": 1761480000.1,
                 "task_start": 1761479990.0, "tools": 4, "sessions": 1,
                 "cwd": "shop-api", "alert": false, "last": 1761480000.1}
  },
  "pet":   {"level": 2, "xp": 160, "xp_level": 100, "xp_next": 300, "energy": 84,
            "mood": "happy", "tasks_today": 5, "tools_today": 30, "errors_today": 0,
            "levelup_at": null, "fed_at": null},
  "usage": {"claude": {"date": "2026-10-26", "input": 0, "output": 0, "cache_read": 0,
                       "cache_write": 0, "messages": 0}},
  "approval": null
}
```

其他接口：

| 接口 | 作用 |
|---|---|
| `POST /hook/<agent>` | hook 原文，可加 `?event=名字`；`?wait=1` 时 `PermissionRequest` 会等按键，返回 `{"decision":"allow"/"deny"}` 或 `{}` |
| `GET` / `POST /api/config` | 读取 / 修改模式和 Agent 列表 |
| `GET /api/agents` | 每个 Agent 的接入配置 |
| `POST /api/button {"button":"B"}` | 模拟 B 键 |
| `POST /api/approval {"id","decision"}` | 回答正在等待的权限请求：`allow` / `deny` / `skip`（交给电脑） |
| `POST /api/demo` | 播放演示 |

## 目录

```
deskpet/agents.py   支持的 Agent、身份识别、各家 hooks 配置生成
deskpet/core.py     hook 事件 → 每个 Agent 的显示状态
deskpet/pet.py      经验、等级、精力
deskpet/usage.py    今日 Claude token 统计
deskpet/server.py   HTTP 守护进程 + SSE + 模式配置
deskpet/approvals.py  按键批准权限：挂起请求、等待决定
deskpet/night.py    夜间息屏：时间段 → 亮 / 暗 / 熄屏
deskpet/demo.py     演示脚本（走真实的 hook 处理流程，按所选 Agent 分配角色）
deskpet/device.py   USB 串口：给固件发状态帧、自动找设备、接收按键
deskpet/weather.py  天气：Open-Meteo 地理编码 + 预报，后台定时刷新
hooks/hook_bridge.py  command hook 转发器（附带身份线索）
web/                网页模拟器（320×240 canvas）
firmware/           ESP32 固件（PlatformIO）和电脑端界面预览工具
tests/              python3 -m unittest discover -s tests
```

## 资料来源

- Claude Code hooks：https://code.claude.com/docs/en/hooks
- Gemini CLI hooks：google-gemini/gemini-cli 仓库 `docs/hooks/reference.md`
- Qwen Code hooks：QwenLM/qwen-code 仓库 `docs/users/features/hooks.md`
- Kimi Code hooks：MoonshotAI/kimi-code 仓库 `docs/en/customization/hooks.md`
- Grok Build：xai-org/grok-build 仓库的配置文档（通知 hooks、读取 `~/.claude/settings.json`）
- DeepSeek 接 Claude Code：https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/
- Codex hooks：openai/codex 源码（codex-rs/hooks：事件名、hooks.json 解析、未信任的 hooks 被跳过；codex-rs/features：hooks 默认开启，codex_hooks 为旧别名）
- Muse Code hooks：第三方资料（meta-models/muse-code-sdk issue、Arcjet 文档），未读到 dev.meta.ai 官方配置页
- DeepSeek Harness：deepseek-ai/deepseek-harness 源码与文档（docs/user/develop：插件、`session/event`、bundle 安装；packages/core/session：事件类型；docs/tool-catalog.md：工具名）
- Open-Meteo 接口参数、返回格式和 WMO 天气代码表：open-meteo/open-meteo-website 仓库里的文档源码；地理编码：open-meteo/geocoding-api（数据来自 GeoNames）

## 下一步

1. 真机实测固件（按键、声音、刷新率、CYD 屏幕方向、按键批准权限），补上 Core2 的声音。
2. 兼容 [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy) 的 BLE 协议，让设备也能连 Claude 桌面版。
3. 原创角色和 GIF 皮肤包。
