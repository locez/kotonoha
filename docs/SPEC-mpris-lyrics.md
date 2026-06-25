# Kotonoha MPRIS + 外部歌词源 — 设计规格 (Spec v0.1)

> 让"只有静态歌词"的播放器(YouTube Music / Spotify / VLC / mpv …)也能动起来:
> 通过 **Linux MPRIS** 拿到正在播放的歌曲信息与进度,从**网易云(优先,尽量逐字)**等外部源
> 抓带时间轴的歌词,复用现有 overlay/clock/karaoke 把它驱动起来。与现有 **Cider 探针共存**。

---

## 1. 目标与范围

- **新增一个通用 provider**:不依赖播放器插件,凡是暴露 MPRIS 的播放器都能用(浏览器里的 YTM/Spotify Web、原生 Spotify、VLC、mpv、Cider 本身也行)。
- 歌词来自**外部源**:**网易云优先**(尽量逐字 YRC,退化逐行 LRC),`lrclib.net` 兜底。
- **与 Cider 探针共存**:Cider 仍走探针(能拿 Apple Music 逐字 TTML,质量最高);其余播放器走 MPRIS。
- **复用现有一切**:`LyricsState / MediaClock / KaraokeLabel / overlay / tick`。数据模型(`LyricLine`/`LyricWord`)**无需改动**。

非目标(v0.1 外):歌词编辑/上传;非 Linux;无 MPRIS 的播放器。

---

## 2. 架构:Provider 抽象

```
                         ┌──────────────────────────────────────────┐
  Cider (探针, 现有) ──WS─▶│ LyricsReceiver ─┐                          │
                         │                 ├─▶ LyricsState ─▶ overlay │
  任意 MPRIS 播放器 ──D-Bus─▶│ MprisProvider ──┘   (snapshot + tick)     │
   (YTM/Spotify/VLC…)    │     │                                       │
                         │     └─▶ LyricsFetcher ─▶ 网易云/lrclib       │
                         └──────────────────────────────────────────┘
```

两个 provider 都最终调用 `LyricsState.update(snapshot)`(切歌/换行)与 `LyricsState.tick(t, playing)`(高频进度校准)。下游完全不变。

**协调(谁在驱动)**:
- 默认**自动**:Cider 探针有连接 → 用 Cider(忽略 MPRIS,避免双重驱动);否则用 MPRIS 选中的活跃播放器。
- 可在设置里强制指定(自动 / 仅 Cider / 仅 MPRIS / 指定某个 MPRIS player)。
- 实现:`ProviderCoordinator` 持有当前 active 源;切换时 `state.clear()`。

---

## 3. MPRIS 接入(D-Bus)

**库**:`dbus-fast`(纯 Python、asyncio 原生,完美配 qasync;`dbus-next` 的高性能后继)。新依赖。

读 `org.mpris.MediaPlayer2.Player`:
| 数据 | 来源 | 用途 |
|---|---|---|
| 标题/艺术家/专辑/时长 | `Metadata`(`xesam:title`/`xesam:artist`/`xesam:album`/`mpris:length`) | 搜歌词 + 时长校验匹配 |
| 播放状态 | `PlaybackStatus`(Playing/Paused/Stopped) | 驱动时钟 |
| 进度 | `Position`(微秒) | tick 校准 |
| seek | `Seeked` 信号 | 立即重锚时钟 |

**进度获取 = 复用现有 tick 机制**:MPRIS 不主动推 `Position`(只有 `Seeked` 信号),所以**每 ~200ms 轮询一次 `Position`** → `state.tick(position_s, playing)`,本地 60fps 插值补平滑。和 Cider 的 tick 一模一样的模型。

**播放器发现与选择**:
- 枚举 `org.mpris.MediaPlayer2.*` bus names;监听 `NameOwnerChanged` 处理出现/消失。
- 选 active player:优先 `PlaybackStatus == Playing` 的;多个时可让用户在设置里选(下拉)。
- 浏览器里的 YTM 经 **KDE Plasma Browser Integration / `playerctld`** 暴露为 MPRIS——需实测其 `Position` 是否真实更新(已知风险,见 §7)。

`MetadataChanged`(`PropertiesChanged`)→ 换歌 → 触发重新抓词。

---

## 4. 歌词获取(LyricsFetcher)

**抽象**:`LyricsSource.fetch(title, artist, album, duration) -> ParsedLyrics | None`。按优先级串联,命中即止;结果按 `(title, artist, duration)` **缓存**(切歌频繁、网络慢)。

**优先级链(按用户决策:网易云优先、尽量逐字)**:
1. **网易云 YRC(逐字)** — 最优,逐字 + 翻译(`tlyric`)+ 罗马音。难点见 §5。
2. **网易云 LRC(逐行)** — 逐字拿不到时退化;公开接口,简单。
3. **lrclib.net(逐行)** — 网易云都没有时兜底;免费、开放、按时长匹配、无鉴权。

**匹配准确度(关键)**:搜索 `title + artist` 往往有 live/remix/翻唱/同名。用 **MPRIS `length` 做时长校验**(容差 ±3s)挑最接近的;标题/艺术家做规范化(去除 "feat."、括号备注、大小写、全半角)。匹配不确定时宁可不显示也不显示错的(可在设置开"宽松匹配")。

**翻译**:网易云 `tlyric` 直接接到现有 `show_translation` / `translation_language`(中文翻译现成)。

---

## 5. 网易云 API 与逐字(最大难点,诚实标注)

- **逐行 LRC**:`GET /api/song/lyric?id=<id>&lv=1&kv=1&tv=1`(weapi/公开),返回 `lrc`(逐行)+ `tlyric`(翻译)。相对简单稳定。
- **逐字 YRC**:网易云的逐字歌词走 **eapi**(`/api/song/lyric/v1`,参数含 `yrc`),**需要请求加密**(AES + 固定 key/RSA),可能还需要登录 cookie。纯 Python 可实现(社区有成熟参考:NeteaseCloudMusicApi 等的加密算法),但**这是本功能工作量与不确定性的主要来源**:
  - 接口/加密参数可能随网易云变动 → 实现时需现网验证。
  - 部分歌曲**根本没有**逐字数据(只有逐行)→ 必须能优雅退化。
  - 可能需要用户提供网易云 cookie(逐字/部分歌)→ 设置里加一项(可选)。
- **加密依赖**:`pycryptodome`(AES/RSA)。新依赖。

**YRC 解析**:逐字格式形如 `[行起,行时长](字起,字时长,0)字(…)字…`,解析为 `LyricLine.words[]`(每词 `start/end`)。需要专门 parser + 单元测试(纯函数,易测)。

> 工程策略:**先把整条链路用逐行跑通**(lrclib / 网易云 LRC),验证 MPRIS→匹配→歌词→驱动 全程 OK,再单独攻 YRC 逐字。逐字是增量,不阻塞前面。

---

## 6. 数据映射(复用现有 model,零改动)

- **LRC 逐行** → `LyricLine(start=该行时间, end=下一行时间, text, translation, words=())` → `has_word_timing=False` → 现有 karaoke **整行扫光**。
- **YRC 逐字** → `LyricLine(..., words=(LyricWord(start,end,text),…))` → `has_word_timing=True` → 现有 karaoke **逐字扫光**。
- `LyricsSnapshot.current/previous/next/around` 由 MPRIS `Position` 选当前行(复用 `find_current_line` 同款逻辑,放 Python 侧)。
- `timing` 标 `"Word"`/`"Line"`,`provider` 标 `"MPRIS:网易云"` 等便于调试。

所以渲染、时钟、双语、逐字高亮**全部自动复用**。

---

## 7. 风险 / 已知坑

1. **网易云逐字 API 加密 + 可得性**(§5)——最大不确定性;降级链兜底。
2. **匹配错歌**——时长校验 + 规范化缓解;宁缺毋滥。
3. **MPRIS `Position` 在浏览器播放器**(YTM)可能不更新/不准——依赖 Plasma Browser Integration / playerctld,需实测;不行则只能逐行近似或提示不支持。
4. **多播放器/无播放器**——协调逻辑 + 设置选择。
5. **网络/限流**——缓存 + 失败静默 + 不阻塞 UI(全 async)。

---

## 8. 模块与依赖

```
src/kotonoha/providers/
  __init__.py
  coordinator.py        # ProviderCoordinator:在 Cider/MPRIS 间选 active 源
  mpris.py              # MprisProvider:dbus-fast 监听 + Position 轮询 → state
src/kotonoha/lyrics/
  fetcher.py            # LyricsFetcher:优先级链 + 缓存 + 匹配/规范化
  netease.py            # 网易云源(LRC + YRC),加密在 netease_crypto.py
  netease_crypto.py     # weapi/eapi 加密(AES/RSA)
  lrclib.py             # lrclib.net 源
  lrc_parser.py         # LRC → LyricLine（纯函数，测试）
  yrc_parser.py         # YRC → LyricLine（纯函数，测试）
  match.py              # 标题/艺术家规范化 + 时长校验（纯函数，测试）
```

新依赖:`dbus-fast`、`pycryptodome`。

**可测**:`lrc_parser`/`yrc_parser`/`match` 是纯函数,CI 全覆盖(无需 GUI/D-Bus/网络)。网络与 D-Bus 部分用 mock/录制响应测。

---

## 9. 配置(新增)

`config.json` 增:`provider_mode`(auto/cider/mpris),`mpris_player`(指定 bus name 或 auto),`lyrics_sources`(顺序,默认 `["netease","lrclib"]`),`netease_cookie`(可选,逐字用),`match_strict`(bool)。

设置面板加一个 **"来源"** tab:provider 模式、MPRIS 播放器选择、歌词源开关/顺序、网易云 cookie、严格匹配。

---

## 10. 里程碑(已按决策调整:直奔逐字,降级链兜底)

1. **M1 — MPRIS 打通 + 验证地基**:`mpris.py` 用 dbus-fast 读 Metadata/Position/PlaybackStatus + 选 active player;先只把"标题/艺术家/进度"打到日志(不抓词)。**关键验证浏览器 YTM 的 `Position` 是否随播放真实前进**——这是整个功能的地基,不行就得先解决。
2. **M2 — 歌词链路端到端(逐字优先 + 降级)**:`netease.py`(YRC 逐字,无 cookie;拿不到退 LRC 逐行)+ `lrclib.py`(兜底)+ `yrc_parser`/`lrc_parser`/`match`/`fetcher`;MPRIS → 匹配 → 歌词 → 驱动 overlay。**端到端可用,逐字优先**;某首没逐字就自动整行扫光。
3. **M3 — 协调与设置打磨**:Cider/MPRIS 共存协调(自动选源)、"来源" 设置 tab、缓存、多播放器选择、错误兜底、文档。

> 实现上仍会**先用 lrclib(最简单)在 M2 内部秒通链路**当冒烟,再叠网易云逐字——但对外交付目标就是逐字,不单列"逐行里程碑"。

---

## 11. 已确认 / 待验证

1. **网易云 cookie** → ✅ 先做**无 cookie**,能拿到多少算多少(逐字可能受限,降级兜底)。
2. **YTM 来源** → ✅ **浏览器版**(经 Plasma Browser Integration / `playerctld` 暴露 MPRIS)。**M1 必须先验证其 `Position` 真实前进**(浏览器播放器是已知风险点)。
3. **顺序** → ✅ 不绕逐行,MPRIS 打通后**直奔逐字 + 降级兜底**。
