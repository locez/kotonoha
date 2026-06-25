# Kotonoha 桌面歌词浮窗 — 设计规格 (Spec v0.1)

> 一个运行在 Linux Wayland 桌面上的现代化、半透明、可穿透的歌词浮窗。
> 复用 BiliHUD 的 `layer-shell-qt` 技术栈，把"弹幕 HUD"换成"逐字卡拉 OK 歌词 HUD"。

---

## 1. 目标与范围

### 1.1 要做什么

- 在屏幕上以**无边框、半透明、毛玻璃质感**的浮窗实时显示当前播放歌曲的歌词。
- 支持 **Apple Music TTML 逐字（word-by-word）卡拉 OK 高亮**，外加翻译行。
- 在 Wayland (`wlr-layer-shell`) 下浮于**全屏应用之上**（看视频 / 玩游戏时也能看歌词）。
- 支持**鼠标穿透（click-through）**：歌词不挡操作。
- 歌词数据来自已有的 Cider 探针插件（`plugins/cider/lyrics`），通过本地 HTTP 推送。

### 1.2 暂不做（v0.1 之外）

- 不内置音乐播放器、不抓取专辑封面渲染背景（可作为后续增强）。
- 不做多播放器后端（仅 Cider 一个 provider，但**架构上预留** provider 抽象）。
- 不做歌词编辑/上传。

### 1.3 设计原则（继承自 `AGENTS.md`）

- **Async-first**：接收服务、状态轮询、网络 I/O 全部 `async`；只有 Qt widget 边界是同步的。
- 用 `qasync` 把 asyncio 事件循环并入 Qt 事件循环。
- Python 3.10+，Ruff 120 列，公共函数加类型注解，结构化数据用 `dataclass`。
- 捕获**窄**异常并带上下文，避免裸 `except Exception`（仅日志边界例外）。

---

## 2. 技术栈（对齐 BiliHUD）

| 关注点 | 选型 | 与 BiliHUD 的关系 |
|---|---|---|
| GUI | **PyQt6** | 相同 |
| 异步集成 | **qasync** | 相同 |
| 本地传输 | **aiohttp WebSocket**（服务端） | 相同库；BiliHUD 用 aiohttp 做 Mirror，这里用其 WS 做 receiver |
| Wayland 浮窗 | **layer-shell-qt**（C++ 桥 + ctypes） | **直接移植** `layer_shell_bridge.cpp` |
| 构建 | **hatchling + hatch-build-scripts** | 相同：构建期编译 `.so` 并 force-include |
| 包管理 | **uv** | 相同 |
| 歌词来源 | Cider TS 探针插件（已存在） | Kotonoha 独有 |

> 关键约束（同 BiliHUD README）：浮于全屏之上依赖 compositor 的 `wlr-layer-shell`。
> KDE Plasma / KWin 与 wlroots 系支持；**GNOME / Mutter 不支持** → 回退为普通置顶窗口。

---

## 3. 系统架构与数据流

```
┌─────────────────┐   WebSocket (持久连接)        ┌──────────────────────────┐
│  Cider 播放器    │ ◀═══════════════════════════▶ │  Kotonoha (Python/PyQt6)  │
│  + lyrics 探针   │   ws://127.0.0.1:28745        │                          │
│  (TS 插件, WS    │   /kotonoha/cider/lyrics      │  ┌────────────────────┐  │
│   客户端)        │                               │  │ LyricsReceiver     │  │  aiohttp WS server
│                  │   事件驱动推送:               │  │ (WS server)        │  │
│  · 连接即全量同步 │   · 切行/播放暂停/seek/换歌   │  └─────────┬──────────┘  │
│  · 心跳带 t      │   · 心跳(~500ms, 带 currentTime)│          │ 解析/归一化  │
│  · 掉线重连(退避)│ ═════════════════════════════▶│  ┌─────────▼──────────┐  │
└─────────────────┘                               │  │ LyricsState        │  │  dataclass + 信号
                                                   │  │ (当前/上/下行、词)  │  │
                                                   │  └─────────┬──────────┘  │
                                                   │            │ pyqtSignal   │
                                                   │  ┌─────────▼──────────┐  │
                                                   │  │ LyricsOverlay       │  │  layer-shell + 透明
                                                   │  │ (Qt 浮窗 / 逐字高亮)│  │
                                                   │  └────────────────────┘  │
                                                   │  ┌────────────────────┐  │
                                                   │  │ Tray + Settings     │  │  QSystemTrayIcon
                                                   │  └────────────────────┘  │
                                                   └──────────────────────────┘
```

**为什么用 WebSocket（而非定时 POST）**：当前探针是每 1s 盲推一次全量 snapshot，**切行最高有 ~1s 延迟**——对歌词体验很糟。WS 改为**事件驱动**：

- 真正发生变化时立刻推（切行 / 播放暂停 / seek / 换歌）→ 切行近乎零延迟；
- 低频**心跳**（~500ms）只带 `currentTime` 做漂移校正；
- **连接即全量同步**：探针 WS `onopen` 先发一帧完整 snapshot；Kotonoha 重启后探针重连并立即补发，无需轮询；
- 持久连接，无连接抖动；双向，Kotonoha 可回发 `resync` / `ack`。
- **代价**：探针侧需要"带退避的重连"逻辑（Kotonoha 可能后启动或重启）——见 §7.2，属标准实现。

**关键点**：探针**已经做了时间对齐**——payload 直接给出 `currentLine / previousLine / nextLine / aroundLines` 和 `currentTime`。Kotonoha 不需要自己跑播放进度定时器去找当前行，只需：
1. 收到帧 → 更新 state；
2. 在两次心跳之间，用本地单调时钟从最近一次 `currentTime` 推进，在 `currentLine.words[]` 上做**逐字进度插值**实现卡拉 OK 扫光（唯一需要本地高频刷新的部分，~60fps QTimer；播放暂停时停表）。

---

## 4. 数据契约（来自 Cider 探针 `types.ts`）

接收端 endpoint（传输从 HTTP POST 改为 WebSocket）：

```
ws://127.0.0.1:28745/kotonoha/cider/lyrics
```

WS 上传输的每一帧 = 一个 JSON 文本消息，结构仍是探针的 `ProbePayload`（外加 `reason: "open" | "change" | "heartbeat"`）。**数据模型不变，只换传输层**。

Python 侧用 `dataclass` 镜像 TS 类型（仅取所需字段，未知字段忽略）：

```python
@dataclass(frozen=True)
class LyricWord:
    start: float | None   # 秒
    end: float | None
    text: str

@dataclass(frozen=True)
class LyricLine:
    index: int
    id: str
    start: float
    end: float
    text: str
    translation: str
    words: tuple[LyricWord, ...]

@dataclass(frozen=True)
class LyricsSnapshot:
    found: bool
    provider: str            # "Apple Music"
    song_id: str | None
    timing: str | None       # "Word" | "Line" | ...
    language: str | None
    current_time: float | None
    current: LyricLine | None
    previous: LyricLine | None
    next: LyricLine | None
    around: tuple[LyricLine, ...]
    title: str | None        # 来自 playback.nowPlayingItem.attributes.name
    artist: str | None
    is_playing: bool
```

> 解析时对字段缺失/类型不符做**防御式**处理；`timing == "Word"` 且 `words` 非空时启用逐字高亮，否则退化为整行高亮。

---

## 5. 模块设计（Python 包结构）

```
src/kotonoha/
├── __init__.py
├── __main__.py
├── main.py                  # entry_point: 装配 QApplication + qasync 事件循环
├── config.py                # 读写 ~/.config/kotonoha/config.json（XDG）
├── lyrics_loader.py         # layer-shell .so 定位/加载/降级判定（移植 layer_shell_loader.py）
├── layer_shell_bridge.cpp   # C++ 桥（移植自 bilihud，改 scope="kotonoha"）
├── build_bridge.sh          # 构建脚本（移植；产物 libkoto-layer.so）
├── model.py                 # 上述 dataclass + payload 解析（纯函数，易测）
├── state.py                 # LyricsState：持有快照，发 pyqtSignal(snapshot_changed)
├── receiver.py              # LyricsReceiver：aiohttp app，把 payload 灌进 state
├── overlay.py               # LyricsOverlay(QWidget)：透明窗口 + layer-shell + 逐字渲染
├── karaoke_label.py         # KaraokeLabel：逐字渐变高亮的自绘 QWidget
├── tray.py                  # 托盘菜单：穿透开关 / 锁定位置 / 设置 / 退出
├── settings_dialog.py       # 设置对话框（字体、位置、不透明度、是否双语）
└── assets/
    └── icon.png
```

**可测试性**：`model.py`（解析）、`lyrics_loader.py`（降级判定）、`state.py`（信号语义）做成纯逻辑、不依赖显示，可在无 GUI 的 CI 里跑（与 BiliHUD 的 `test_danmaku_format.py` / `test_layer_shell_loader.py` 同思路）。

---

## 6. Layer Shell 桥接（核心，移植 BiliHUD）

### 6.1 C++ 桥

直接复用 `layer_shell_bridge.cpp`，导出 `extern "C"` 函数：

| 函数 | 作用 | 歌词浮窗用法 |
|---|---|---|
| `make_overlay(win)` | 提升为 `LayerOverlay` 层、`ExclusiveZone=-1`、设 anchor、`setScope("kotonoha")` | 默认锚定**顶部居中**（anchor = Top，margin 控制离顶距离） |
| `set_passthrough(win, bool)` | 设空/NULL input region 实现鼠标穿透 | **默认开启穿透**（歌词是被动展示） |
| `set_anchor_position(win, x, y)` | 通过 margins 调整位置 | 设置里微调上下/左右偏移 |
| `set_keyboard_interactivity(win, bool)` | 键盘交互 | 默认 `None`（歌词不需要键盘焦点） |

> **完全对齐 BiliHUD 的做法**（这些都是踩坑后确认的关键点）：
> - anchor 用 **`Top|Left`**，靠 **左/上 margins 定位**（`set_anchor_position(x,y)`），这样面板可**自由拖动**。
> - 窗口必须有**显式、非零的固定尺寸**（≈屏宽 90%×由字号算出的高度），**不能用 `adjustSize()` 收缩**（否则 surface 变得极小/不可见——早期 bug）。内容在固定窗口内居中。
> - `make_overlay()` **必须在 `show()` 之前调用**：窗口一旦以普通 xdg surface 映射，LayerShellQt 就无法再转成 layer surface（报错 *"already has a shell integration"*）。激活流程：`winId()` → `windowHandle()` → `sip.unwrapinstance` → `make_overlay` **→ 然后才 `show()`**。
> - 拖动 = 改 margins（Wayland 禁止客户端 `self.move()`）：用**局部坐标**记录抓取点，`layer_pos += diff`，调 `set_anchor_position` 后 `self.update()` 触发 `wl_surface.commit`（X11 回退才用 `self.move()`）。

### 6.2 加载与降级（移植 `layer_shell_loader.py`）

- `should_disable_layer_shell(platform, desktop)`：Wayland + GNOME → 禁用 layer-shell。
- `find_layer_shell_library(pkg_dir)`：找 `libkoto-layer.so`。
- 找不到 / GNOME / X11 → **优雅降级**为 `FramelessWindowHint | WindowStaysOnTopHint` 的普通置顶窗口（不再保证浮于全屏之上，但桌面可用）。

### 6.3 激活时序

照搬 BiliHUD：构造 widget → `activate_layer_shell()`（在 `show()` 之前先尝试一次，并 `QTimer.singleShot(100, ...)` 再补一次，确保 surface 映射后生效）。

---

## 7. 接收服务（aiohttp WebSocket）

### 7.1 服务端（Kotonoha）

```python
# receiver.py
class LyricsReceiver:
    def __init__(self, state: LyricsState, host="127.0.0.1", port=28745): ...
    async def start(self) -> None:   # aiohttp.web.AppRunner + TCPSite
    async def stop(self) -> None:
    async def _ws(self, request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        async for msg in ws:                      # 持续读帧
            if msg.type == web.WSMsgType.TEXT:
                snapshot = parse_payload(json.loads(msg.data))  # model.py 纯函数
                self.state.update(snapshot)                     # 触发 pyqtSignal
        return ws
```

- 路由：`GET /kotonoha/cider/lyrics`（WS upgrade）。
- 仅监听 `127.0.0.1`（本机，隐私）。
- 端口可在 config 覆盖（默认 `28745`，对齐探针默认 `CIDER_LYRICS_PROBE_PORT`）。
- 用 `qasync` 事件循环承载 aiohttp，**与 Qt 同循环**，无需额外线程。
- 容错：单个客户端断开/坏帧不影响服务端；服务端长期 `listen`，等探针随时重连。
- （可选）保留一个 `POST` 调试路由，便于用 curl 灌测试帧——不是主路径。

### 7.2 客户端（Cider 探针，需改造）

把 `main.ts` 里"`setInterval` + `fetch POST`"换成 WS 客户端：

- 维护一个到 `ws://127.0.0.1:28745/...` 的连接；
- `onopen` → 立即发一帧完整 snapshot（`reason: "open"`），并启动心跳定时器（~500ms，`reason: "heartbeat"`）；
- 在播放状态变化点（切行、播放/暂停、seek、换歌）**事件驱动**地发 `reason: "change"`；
- `onclose / onerror` → **指数退避重连**（如 0.5s→1s→2s→…上限 ~5s），Kotonoha 没开时安静重试；
- 受影响文件：`plugins/cider/lyrics/src/main.ts`、`src/probe/types.ts`（`ProbeConfig.endpoint` 语义改为 ws URL）；`scripts/receive.mjs` 调试接收器一并改成 WS（或保留 HTTP 调试旁路）。
- 探针的 payload 构造（`createProbePayload` / `probe/*`）**无需改动**，复用现有逻辑。

---

## 8. 透明与穿透（必须满足的"特性"）

照搬 BiliHUD 的玻璃化做法，并叠加歌词专用增强：

1. **窗口级透明**
   - `setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)`
   - `setWindowFlags(FramelessWindowHint | WindowStaysOnTopHint | Window)`
2. **自绘背景**（`paintEvent`）
   - 抗锯齿圆角 + 半透明深色底（如 `QColor(15, 17, 22, ~110)`），营造"毛玻璃药丸"质感；
   - **可切换为"纯文字 + 描边/阴影、无底板"模式**（最沉浸，适合全屏看视频）。
3. **文字可读性**
   - `QGraphicsDropShadowEffect`（深色阴影/外发光）让浅色字在任意背景上都清晰——这是歌词浮窗在亮背景下可读的关键。
4. **鼠标穿透 + HUD 锁**
   - 默认 `set_passthrough(True)`：歌词完全不挡点击；
   - HUD 上有一个 **🔒/🔓 锁图标**（外加 ⚙ 设置）：解锁状态下可直接**拖动浮窗**定位、点锁回到穿透；
   - 因穿透时 HUD 自身也不接收点击，**解锁入口**放在托盘（左键单击托盘图标或菜单项即可解锁）。拖动落点会写回 `margin_edge/margin_x`。
5. **整体不透明度**
   - `setWindowOpacity()` 或样式 alpha，设置里滑杆可调（30%–100%）。

---

## 9. 视觉设计（现代化）

参考 BiliHUD 的 rgba 玻璃风、`qlineargradient`、圆角、`Microsoft YaHei`/`Segoe UI` 字体族，做歌词专属的"Apple Music 风"排版：

- **顶部居中三行布局（默认）**：浮窗锚定屏幕**顶部居中**，自上而下：上一行（暗淡小字）/ 当前行（大字 + 逐字高亮）/ **翻译行（默认显示，双语）** / 下一行（暗淡小字）。
- **逐字卡拉 OK 高亮**（`KaraokeLabel`，自绘）：
  - 已唱过的词 = 亮色（粉色渐变填充），未唱 = 半透明白（如 `rgba(255,255,255,90)`）；
  - 当前正在唱的词用 `current_time` 在 `word.start→word.end` 间做**线性进度**，以"扫光/渐变裁切"方式从左到右填充（`QLinearGradient` + clip）；
  - 平滑由本地 ~60fps `QTimer` 插值驱动，不依赖网络推送频率。
- **品牌强调色 = 粉色**：默认热粉渐变 **`#FF4FA3 → #FF8FCB`**（已唱词的填充与发光主色），当前词扫光高亮用更亮的 `#FF6EC7`。可在设置里换色。
- **入场/切行动画**：切到下一行时做轻微淡入 + 上移（`QPropertyAnimation`，~180ms），现代且不喧宾夺主。
- **字号/字重**：当前行 `font-weight: 800`、字号设置可调（默认 ~22px）；上下行 ~14px、alpha 较低。
- **空状态**：无歌词 / 暂停时浮窗淡出或显示极简"♪ 标题 — 歌手"。

> 所有样式集中在一处 `STYLE` 常量 + `paintEvent`，避免散落，便于后续做主题。

---

## 10. 托盘、设置面板与配置

**精简托盘**（不再像 BiliHUD 那样把所有功能平铺在右键里）：
- 锁定 / 鼠标穿透（勾选项）；左键单击托盘图标 = 快速解锁/锁定
- 设置…（打开下面的设置面板）
- 退出

**Tab 设置面板**（`settings_dialog.py`，`QTabWidget`，更专业）：
- **外观**：字号、不透明度、背板样式（玻璃面板 / 纯文字）
- **歌词**：逐字高亮开关、显示翻译、**翻译语言**（自动跟随系统 / 简中 / 繁中 / EN / JA / …）
- **位置**：顶部/底部、距边缘、水平偏移、默认穿透
- **连接**：WebSocket 端口（改后需重启 + 同步探针）

**双语 / 翻译语言**：Apple Music TTML 内含多语言翻译（`<translation xml:lang>`）。Kotonoha 把首选语言（默认由 `QLocale.system()` 推断，见 `i18n.py`）通过 WS **控制帧** `{"type":"kotonoha/config","translationLanguage":"zh-Hans"}` 推给探针；探针据此从 TTML 抽取对应译文（`setPreferredTranslationLanguage` 会清缓存触发重解析）。设置里改语言即时广播给已连接探针。

- **config.py**：`~/.config/kotonoha/config.json`（XDG_CONFIG_HOME），字段：
  `port(28745), anchor_top(默认 true), margin_edge, margin_x, font_size, opacity, show_translation(默认 true), translation_language(默认 "auto"), accent_start/end/sweep(默认粉色), passthrough(默认 true), karaoke(默认 true), panel_style(pill/text)`。

---

## 11. 打包与构建（移植 BiliHUD 的 hatch hook）

`pyproject.toml`：

```toml
[build-system]
requires = ["hatchling", "hatch-build-scripts"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel.force-include]
"src/kotonoha/libkoto-layer.so" = "kotonoha/libkoto-layer.so"

[tool.hatch.build.hooks.build-scripts]
[[tool.hatch.build.hooks.build-scripts.scripts]]
commands = ["bash src/kotonoha/build_bridge.sh"]
artifacts = ["src/kotonoha/libkoto-layer.so"]

[project]
dependencies = ["PyQt6", "qasync", "aiohttp"]
```

- 系统依赖（README 需补充，照 BiliHUD）：`qt6-base`、`qt6-wayland`、`layer-shell-qt`、`wayland`、qmake/pkg-config、`g++`。
- 运行：`uv sync && uv run kotonoha`。
- **Cider 探针**保持独立 Vite/pnpm 构建（已有），README 写清"先装探针 → 启动 Kotonoha → 播歌"流程。

---

## 12. 测试

沿用 BiliHUD 的"纯逻辑可测"策略，放在 `tests/`：

- `test_model.py`：payload → `LyricsSnapshot` 解析（含字段缺失、`timing != Word`、空 words、脏数据）。
- `test_lyrics_loader.py`：`should_disable_layer_shell` / `find_layer_shell_library` 降级判定（移植 BiliHUD 同名测试）。
- `test_receiver.py`：用 `aiohttp` 测试客户端 POST 一个 payload，断言 state 收到对应快照、返回 204。
- `test_state.py`：信号在快照变化时发射、相同快照不重复发射的语义。
- `test_karaoke.py`：给定 `current_time` 和 words，计算"已唱进度/当前词索引/词内进度"的纯函数正确（高亮渲染的算术部分抽成纯函数测）。

GUI 渲染本身不在 CI 跑（无显示环境），逻辑全部下沉到纯函数。

---

## 13. 实施里程碑

1. **M0 — 项目脚手架对齐**：升级 `pyproject.toml`（build hook + 依赖）、建包结构、移植 `build_bridge.sh` + `layer_shell_bridge.cpp`（改 scope/产物名）、`lyrics_loader.py` + 测试。
2. **M1 — 数据链路打通（WS）**：`model.py` 解析 + `state.py` + `receiver.py`（aiohttp WS 服务端）；**改造探针 `main.ts` 为 WS 客户端**（连接/全量同步/心跳/退避重连）；端到端 smoke：探针推送能进 state（先 print，不画 UI）。
3. **M2 — 透明浮窗**：`overlay.py` 基础透明窗 + layer-shell 激活 + 默认穿透 + **顶部居中**；显示"当前行整行"。
4. **M3 — 逐字卡拉 OK + 现代样式**：`karaoke_label.py` 扫光高亮、三行布局、翻译行、阴影/发光、切行动画。
5. **M4 — 托盘与设置**：穿透切换、拖动定位、`settings_dialog.py`、config 持久化。
6. **M5 — 降级与打磨**：GNOME/X11 回退、空状态/暂停、README + 系统依赖文档、打包验证。

---

## 14. 设计决策（已定）

| # | 决策 | 选定 |
|---|---|---|
| 1 | 传输协议 | **WebSocket**（aiohttp 服务端 + 探针 WS 客户端，事件驱动 + 心跳 + 退避重连） |
| 2 | 默认布局 | **顶部居中**三行（上一行 / 当前行 / 翻译 / 下一行） |
| 3 | 高亮粒度 | **逐字卡拉 OK 扫光**（`timing=="Word"` 时；否则退化整行） |
| 4 | 默认锁定 | **首次启动为解锁**（可交互，方便拖动定位）；定位后锁定即穿透并持久化。HUD 上 🔒/🔓 图标 + 托盘左键切换 |
| 5 | 双语 | **默认显示翻译行**；翻译语言默认跟随系统（`QLocale`），设置可改，经 WS 控制帧推给探针 |
| 6 | 品牌主色 | **粉色** `#FF4FA3 → #FF8FCB`（扫光高亮 `#FF6EC7`），可设置换色 |
| 7 | 交互形态 | 托盘精简（锁/设置/退出）；详细配置进 **Tab 设置面板**（外观/歌词/位置/连接） |

### 仍可后续微调（不阻塞动工）

- 心跳频率（默认 ~500ms）与退避上限（默认 ~5s）的具体数值，可在联调时按手感调。
- 是否保留一个 HTTP POST 调试旁路（便于 curl 灌测试帧）——倾向保留，零成本。
