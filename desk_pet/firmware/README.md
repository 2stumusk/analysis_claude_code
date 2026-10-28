# Desk Pet 固件（ESP32）

把网页模拟器里的那块 320×240 屏幕做成真机：USB 线插到电脑上，供电和数据走同一根线，电脑上的 deskpet 守护进程负责把 Agent 状态推给板子。

**当前状态**：三块目标板都已**编译通过**，界面经过本机预览检查，串口协议和守护进程之间的通信也有自动化测试。但**还没有在真机上跑过**，拿到板子后需要实测。

## 支持的板子

| 板子 | 编译目标 | 按键 | 声音 | 指示灯 |
|---|---|---|---|---|
| M5Stack Basic / Gray | `m5stack-core` | 实体键 A B C | 板载喇叭（GPIO25） | 无 |
| M5Stack Core2 | `m5stack-core2` | 屏幕下方的触摸条，分成 A B C 三段 | 暂不支持 | 无 |
| ESP32-2432S028R（俗称 CYD） | `cyd` | 触摸屏：左半边 A，右半边 B，长按任意处 C | 喇叭接口（GPIO26，经功放） | RGB 灯（4/16/17，低电平点亮） |

- 屏幕和触摸芯片由 LovyanGFX 自动识别。CYD 的 ILI9341 和 ST7789 两种屏幕版本都在它的识别列表里。
- CYD 的扬声器和 RGB 灯引脚来自社区文档 [witnessmenow/ESP32-Cheap-Yellow-Display 的 PINS.md](https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display/blob/main/PINS.md)。
- 推荐先用 **M5Stack Basic**：自带外壳、实体按键和喇叭，最接近成品形态。

## 按键

| 键 | 作用 |
|---|---|
| A | 切换页面：表情 → 时钟 → 天气 → Agent 列表 → 宠物（只在电脑端勾选的页面之间切换） |
| B | 有提醒时确认，没有提醒时喂食（发给守护进程处理，和网页上的 B 一样） |
| C / 长按 | 开关声音，设置会记住 |

## 刷机和使用

```bash
pip install platformio
cd desk_pet/firmware
pio run -e m5stack-core -t upload       # 换成你的板子：m5stack-core2 / cyd

cd ..
python3 -m deskpet --serial auto        # 自动找到设备；也可以写 /dev/ttyUSB0、COM3
```

- 守护进程会扫描 USB 串口，等固件发来 `hello` 就算连上。连上后网页右上角会显示"USB 设备 …"。
- macOS 和 Linux 不需要额外装包。Windows 需要先装 `pip install pyserial`。
- 很多 ESP32 板在串口被打开时会自动复位一次，属于正常现象，复位后会自动重连。
- 平台用的是社区维护的 [pioarduino](https://github.com/pioarduino/platform-espressif32)（Arduino-ESP32 3.x）。PlatformIO 官方的 espressif32 平台还停留在 Arduino 2.x。

## 串口协议

波特率 115200，每行一条 JSON。

**电脑 → 设备**：状态有变化时立即发送，否则至少每 5 秒发一次心跳，设备靠它校准时钟、判断连接是否还在。

```json
{"v":1,"t":1793059190,"tz":28800,"f":0,
 "a":[{"id":"claude","l":"CLAUDE","b":"CL","s":"running","d":"npm test","c":"shop-api","e":12,"n":4,"k":1,"x":0}],
 "p":{"lv":2,"xi":30,"xs":200,"en":84,"md":"happy","tk":5,"tl":30,"er":0,"lu":-1,"fd":-1},
 "u":{"o":1234,"t":5678},
 "pg":"fcw",
 "w":{"st":"ok","c":"Wuxi","tx":"Light rain","k":"rain","dy":1,"t":17,"fl":16,"hu":82,"ws":14,
      "hi":21,"lo":14,"p":70,"ag":5,"sm":0,"h":[[15,19,"partly",40,1]]}}
```

- 文字只发可打印 ASCII，因为设备字体只有这些字符，中文会变成 `?`。
- 长度会截断（detail 最多 48 字符），最多 8 个 Agent，一行最长不超过 4 KB。
- 计时类的字段（`e` 任务已用时、`lu`/`fd` 升级和喂食后过了多久）只发起点，之后由设备自己往上数。

**设备 → 电脑**：
- 开机后每 2 秒发一次 `{"hello":"deskpet","fw":"0.1.0","board":"m5stack-basic"}`，直到收到第一帧。
- 按下 B 时发 `{"btn":"B"}`。

`pg` 是启用的页面（f 表情、c 时钟、w 天气、a 列表、s 宠物）。`w` 是天气：没设城市时为 `null`；`k` 是图标类型，取值有 clear、partly、cloudy、fog、drizzle、rain、snow、thunder；`h` 是接下来的逐 2 小时预报。

解析器在 `src/frame.cpp`，是固件自带的约 150 行小 JSON 解析器，不依赖 ArduinoJson，所以在电脑上也能跑测试。

## 代码结构

```
src/gfx.h        UI 用的精简绘图接口（矩形、圆、三角、圆弧、粗线、文字）
src/gfx_lgfx.h   在设备上把它转给 LovyanGFX 精灵图（Sprite）
src/ui.cpp       四个页面 + 表情动画，逻辑和 web/sim.js 一一对应
src/frame.cpp    串口帧解析
src/model.h      设备端的数据模型
src/main.cpp     板子识别、按键、蜂鸣器、串口、分段渲染
tools/preview_main.cpp + tools/preview.py   电脑上的界面预览
```

**分段渲染**：一整屏 16 位色的精灵图要 150 KB，没有 PSRAM 的板子（Basic、CYD）放不下，所以把屏幕切成上下两段（每段 320×120，76.8 KB），同一套绘图代码按偏移各画一次再推到屏幕；内存再紧会自动切成更多段。有 PSRAM 的 Core2 一次画整屏。每段之间会顺便读一次串口，避免接收缓冲区溢出。

## 在电脑上预览界面

```bash
python3 tools/preview.py --lgfx /path/to/LovyanGFX --out preview/
```

工作方式：
- 把 `ui.cpp`、`frame.cpp`、`model.cpp` 和一个"记录型"绘图接口一起编译成本机程序，**不链接 LovyanGFX**。
- 场景帧由守护进程的 `deskpet/device.py` 真实生成。
- 记录下来的绘图指令用 Pillow 画出来。文字按 LovyanGFX 字体文件里的字形数据逐像素绘制，字形和宽度与设备一致。图形用 Pillow 近似绘制，圆角和抗锯齿会和真机略有出入。

输出 24 张 PNG 外加一张总览图 `sheet.png`，覆盖：
- 9 种表情（离线、思考、读文件、改代码、跑命令、需要你、完成、出错、饿了）
- 1 / 2 / 3 / 8 个 Agent 时的布局
- 时钟页、宠物统计页
- 天气页：雨、晴夜、雷暴、雪、未设城市，以及只开 3 个页面时的页码圆点。天气数字是标明了 "sample data" 的样例

## 同类开源固件（可借鉴之处）

Star 数为 2026-10-26 在 GitHub 页面上看到的取整值。

| 项目 | Star | 硬件 / 做法 | 借鉴了什么 |
|---|---|---|---|
| [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy) | 2.7k | M5StickC Plus，BLE 连 Claude 桌面版，按键批准 / 拒绝 | 宠物 7 种状态动画的划分；后续可以兼容它的 BLE 协议 |
| [HermannBjorgvin/Clawdmeter](https://github.com/HermannBjorgvin/Clawdmeter) | 2.3k | ESP32-S3 AMOLED，显示用量 + 吉祥物 | 证明了"萌 + 实用"的需求；注意它提醒的版权素材问题 |
| [zxkill/agentface32](https://github.com/zxkill/agentface32) | 2 | M5Stack Basic 等，多 Agent 表情，Wi-Fi hooks | 多 Agent 和事件映射的思路 |
| [nsyll/clawdometer-eink](https://github.com/nsyll/clawdometer-eink) | 6 | 墨水屏 + BLE + 电池 | 低功耗和墨水屏方向，可作为以后的选项 |
| [FluxGarage/RoboEyes](https://github.com/FluxGarage/RoboEyes) | 928 | OLED 机器人眼睛动画库 | 眼睛造型思路。它是 GPL-3.0，本固件没有使用它的代码，眼睛是自己画的 |

和它们不同的地方：
- 走 USB 串口，不需要配 Wi-Fi，prompt 内容也不会出现在局域网上。
- 同时支持 8 家 Agent。
- 设备和网页模拟器共用同一份协议和同一套界面逻辑，电脑上就能预览。

## 已知限制 / 还没验证的

- **没上过真机**：按键手感、声音大小、刷新率（目标 30 fps）、CYD 屏幕方向，都要拿到板子实测。
- Core2 的喇叭要用 I2S 驱动并通过电源芯片打开，暂时没做，所以 Core2 没有声音。
- CYD 的 ST7789 版本如果颜色不对（反色），需要在 LovyanGFX 配置里调整。
- 设备端没有中文字体，Agent 的 detail 里的中文会显示成 `?`。
