# 歌词、缓存和手动选词

[English](SPEC-lyrics.md)

本文定义歌词来源、解析、SQLite cache 和手动选词之间的模型与行为边界。

## 核心模型

- `TrackIdentity` 和 `PlaybackObservation` 是各播放适配器输出的规范化播放事实。
- `TrackMetadata` 是歌词匹配和搜索使用的 provider-neutral metadata。
- `LyricsArtifact` 保存 provider identity、原始 payload、解析后的完整歌词和匹配度。
- `LyricsDocument` 是完整时间轴；展示层从中计算当前行、上下文、逐字进度和 interlude。
- `LyricsSourceResult` 携带 `source_id`、document、匹配度、时长、cache artifact 和 source kind。

## 来源目录

| 类型 | 来源 | 能力 |
| --- | --- | --- |
| `local` | sidecar、embedded | 只处理播放器提供的 exact hint |
| `network` | Netease、QQ Music、LRCLIB、Kugou | metadata 搜索或 song ID 精确获取 |
| `live` | Cider HTTP、generic adapter | 提供当前播放候选 |

默认歌词来源顺序为：

```text
netease -> lrclib -> kugou -> cider
```

`lyrics_sources` 控制歌词 provider；`display_sources`（默认
`mpris -> cider -> adapter`）控制播放事实和实时歌词候选。两者是独立配置。
QQ Music 只支持 exact song ID，Cider 只提供当前播放器轨道；两者没有
metadata manual-search capability，搜索界面会返回具体的 unavailable reason。

## 解析策略

LRC 解析器同时支持普通行级时间标签和 Enhanced LRC 的 inline
`<mm:ss.xx>` 时间标签。inline 标签会被规范化为 `LyricWord`；没有 inline
标签的输入仍然是行级歌词。每个词的结束时间取下一个 inline 标签，或在行末
取该行的结束时间。

每个稳定的 MPRIS track 有独立 generation。旧 generation 的 task 会被取消，过期结果不能更新当前显示。

自动解析优先级如下：

1. exact hint 路径先查匹配的 `MANUAL` cache，再查 hint 指定的 source。
2. 普通 source plan 先查与当前 track 匹配的 `MANUAL` cache。
3. `prefer_best_lyrics` 开启时按匹配度竞争候选，配置顺序只打破平局；关闭时按配置顺序遇到第一个有效结果即停止。
4. 普通 cache 只作为所属 provider 的 automatic cache 命中；网络异常不会伪装成 miss。

## SQLite cache

`LyricsCache` 是异步 facade，`LyricsCacheStorage` 通过注入的 worker 执行同步 SQLite。默认路径为 `$XDG_CACHE_HOME/kotonoha/lyrics.sqlite3`，schema version 为 `1`，默认最多保留 `1000` 条，按 `last_accessed` 淘汰。

记录 key 为 `(provider, provider_song_id)`，保存 provider metadata、payload、时间、mode 和版本信息。损坏或不包含 timed lines 的 payload 会被删除并视为 miss。

| mode | 含义 |
| --- | --- |
| `AUTO` (`auto`) | 普通解析在高置信度时写入，只服务所属 provider 的自动命中 |
| `MANUAL` (`manual`) | 用户确认的结果，普通解析和 exact hint 都优先匹配 |

公开操作：

| 操作 | 用途 |
| --- | --- |
| `search(query)` | 按标题、艺术家、专辑、provider 或 song ID 模糊搜索，按最近使用排序 |
| `get(key)`、`count()` | 读取单条 metadata 或总数 |
| `upsert(artifact, mode)` | 创建或替换记录 |
| `update(key, artifact, mode)` | 更新已有记录，供歌词 workflow 使用；管理页面不提供编辑入口 |
| `delete(key)`、`delete_many(keys)`、`clear()` | 删除单条、批量删除或清空 |
| `lookup()`、`lookup_manual()` | resolver 专用的内容命中 |

缓存管理页面只使用 metadata search 和 delete/clear。它与 resolver 共享同一个 `LyricsCache`，但通过窄的 management/write port 接入，不依赖完整 MPRIS facade。

## 手动搜索和应用

悬浮窗的查找按钮打开 modeless 搜索窗口。标题、艺术家和专辑预填且可编辑，当前时长只读展示。

搜索服务并发查询已选 provider：每个 provider 最多返回 `30` 个候选，一次搜索最多向 UI 暴露 `90` 个结果，并按 `provider:provider_song_id` 去重。列表显示来源、标题、艺术家、专辑、时长、歌词格式、翻译可用性和匹配度。不可用 provider 以带 `source/reason` 的 typed result 返回。

应用候选时：

1. 以 `MANUAL` mode 写入共享 cache。
2. 调用 `DisplayCoordinator.apply_manual_artifact()`。
3. 仅当当前播放 track 仍匹配搜索 track 时替换 document。
4. 立即按当前播放位置重新投影，播放中无需等待下一首。
5. 刷新搜索窗口的来源状态。

搜索窗口分别显示当前歌词 provider、获取方式、播放事实来源（MPRIS/Cider/adapter）和 cache 状态（未使用/自动 cache/手动选择）。切歌后手动 document 不覆盖新 track，新 track 按当前 source policy 重新解析。

## 本地来源和失败处理

sidecar 和 embedded 在 local worker 中读取，不写入 network cache，origin 分别为 `sidecar` 和 `embedded`。

provider 的 transport、解析和 payload 错误在边界处转换为窄 exception 或 typed unavailable result；cache 失败必须报告 `LyricsCacheError`，不能返回虚假成功。
