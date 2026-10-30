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
| `network` | AMLL TTML DB、Netease、QQ Music、LRCLIB、Kugou | metadata 搜索或 song ID 精确获取 |
| `live` | Cider HTTP、generic adapter | 提供当前播放候选 |

默认歌词来源顺序为：

```text
amll -> netease -> lrclib -> kugou
```

Cider 探测默认关闭，只有在 `lyrics_sources` 中启用 `cider` 后才开始轮询。
已有配置中保存的来源选择会保留，需要在“设置 → 来源”中勾选 AMLL 才会将它加入已有配置。

`lyrics_sources` 控制歌词 provider；`display_sources`（默认
`mpris -> cider -> adapter`）控制播放事实和实时歌词候选。两者是独立配置。
QQ Music 只支持 exact song ID，Cider 只提供当前播放器轨道；两者没有
metadata manual-search capability，搜索界面会返回具体的 unavailable reason。

## 解析策略

LRC 解析器同时支持普通行级时间标签和 Enhanced LRC 的 inline
`<mm:ss.xx>` 时间标签。inline 标签会被规范化为 `LyricWord`；没有 inline
标签的输入仍然是行级歌词。每个词的结束时间取下一个 inline 标签，或在行末
取该行的结束时间。

TTML 从 AMLL TTML DB、`.ttml` sidecar 和内嵌歌词文本读取。解析范围为 Apple/AMLL 常见歌词形式：
带命名空间或无命名空间的 `tt/body/div/p/span`，歌曲绝对时间位置
`hh:mm:ss.fraction`、`mm:ss.fraction` 和带 `h/m/s/ms` 单位的时间，
`begin/end`、`begin/dur`、混合文本、嵌套 span、`br` 和继承的 `xml:space`。
段落时间缺失时可从完整的逐字时间推导。`ttm:role="x-translation"` 转为行翻译；
当前单主唱时间轴不显示罗马音和 `x-bg` 和声。暂不实现字幕布局、顺序容器、帧/tick
时间或非 media 时间基准。无效或不支持的 XML 视为 miss，允许回退到 LRC。
在实体扩展前拒绝 DTD，并限制输入大小、树深度、节点数、行数和词数；不读取 XML 引用的文件或 URL。

AMLL 直接下载原始 TTML；网易云优先解析 YRC，再回退 LRC；酷狗优先 KRC，
再回退 LRC；LRCLIB 和 QQ 音乐读取 LRC；Cider/通用适配器提供规范化行和词。
Enhanced LRC 的逐字时间与 YRC、KRC、TTML 同等参与优先选择，格式名称本身不代表有可用逐字时间。

每个稳定的 MPRIS track 有独立 generation。旧 generation 的 task 会被取消，过期结果不能更新当前显示。

自动解析优先级如下：

1. exact hint 路径先恢复播放 track 的手动绑定（或匹配旧 `MANUAL` 记录），再按配置顺序尝试能理解该平台 ID 的已启用来源。本地文件提示使用本地来源；即使未启用网易云，AMLL 也能按网易云 ID 查询。最佳匹配模式优先 exact 结果中的逐字版本，也可用其他来源中同等匹配度的逐字歌词替换逐行 exact 结果。各来源失败互不影响；找不到更好结果时保留有效的 exact 结果。顺序模式返回第一个有效 exact 结果。
2. 普通 source plan 先恢复相同的手动绑定，再评估自动来源。
3. `prefer_best_lyrics` 开启时依次比较匹配度、实际逐字时间、配置顺序。缓存、实时或网络的逐行候选不能阻止或取消仍可能返回逐字歌词的来源。最高优先级的高匹配度逐字结果仍可跳过多余请求；缓存命中不会重抓其所属 provider。关闭时按配置顺序遇到第一个有效结果即停止。
4. 普通 cache 只作为所属 provider 的 automatic cache 命中；网络异常不会伪装成 miss。

## AMLL TTML DB

`amll` 来源读取上游
[`metadata/raw-lyrics-index.jsonl`](https://github.com/amll-dev/amll-ttml-db/blob/main/metadata/raw-lyrics-index.jsonl)
曲库，并在 `raw-lyrics/` 下下载通过验证的文件名，两者都使用固定的
`raw.githubusercontent.com/amll-dev/amll-ttml-db/main/` 地址。无需账号或本地播放器 API，
不依赖搜索网站的私有接口。

索引元数据在边界解析为带类型的候选和平台 ID。自动匹配复用标题、别名、歌手和录音版本规则；
同等匹配证据下先尝试较新的投稿，但会保留符合匹配条件的旧稿，直到下载和解析确认歌词可用；
新版文件缺失或不支持时，不能因此排除可用的旧稿。手动结果在解析后按共享平台 ID 去重，
保留首个可用结果。手动搜索支持标题、歌手、专辑关键词，
允许用户明确选择较低匹配度的结果。曲库没有承诺音频总时长，因此保留未知时长，不用歌词结束时间代替。
调用方提供 ID 时，可精确查询网易云、QQ、Apple Music 和 Spotify 命名空间；MPRIS 提示提取仍限于
现有已知播放器。QQ 元数据使用 song mid，不能与数字 song ID 混用。

自动和手动查询共享一小时有效的内存索引，刷新串行执行。索引最多 8 MiB、20,000 行 JSONL，
HTTP 超时 15 秒；单个 TTML 最多 2 MiB，HTTP 超时 8 秒。自动查询在 25 秒内尝试最多三个匹配投稿，
精确 ID 查询也在相同预算内尝试最多三个适用版本。手动查询在 45 秒内下载最多 30 个投稿，
并发数为 4，再对可用结果去重。单个下载失败不丢弃其他有效候选；
曲库不可用时报告来源失败，允许其他来源继续返回结果。

来源目录拥有解析和匹配 worker；应用退出时先停止手动搜索和 resolver 任务，再关闭 worker。
HTTP 会话及请求由调用方拥有，手动下载统一取消并等待。解析和匹配在事件循环之外执行；
被取消的阻塞工作可以完成，但不能发布索引。不启动后台刷新任务，也不持久化索引文件。
自动匹配、精确查询和手动选择沿用 SQLite 缓存，以不可变投稿文件名为键保存原始 TTML。
搜索结果按实际内容显示逐行或逐字精度，不假定所有 TTML 都有逐字时间。

## SQLite cache

`LyricsCache` 是异步 facade，`LyricsCacheStorage` 通过注入的 worker 执行同步 SQLite。默认路径为 `$XDG_CACHE_HOME/kotonoha/lyrics.sqlite3`，schema version 为 `1`，默认最多保留 `1000` 条，按 `last_accessed` 淘汰。

记录 key 为 `(provider, provider_song_id)`，保存 provider metadata、payload、时间、mode 和版本信息。损坏或不包含 timed lines 的 payload 会被删除并视为 miss。

手动搜索另外在 `lyric_selections` 中保存原始播放标题、艺术家和时长（四舍五入到 0.1 秒）
到 provider 记录的绑定。专辑信息不参与绑定，因为播放器可能省略或改变它。元数据字符串精确匹配，版本和艺术家保持区分；搜索框编辑和 provider
元数据不改变播放身份。再次选择只替换该歌曲的绑定，重启后仍有效。普通解析和 exact hint
优先恢复绑定，作为用户确认的结果，不再经过自动匹配；自动内容写入不能覆盖绑定。
删除、清空或丢弃损坏歌词会同时清除绑定。手动记录及其绑定不参与自动 LRU 淘汰，LRU 限制只作用于自动记录；cache-enabled 设置仍控制恢复。

旧数据库自动增加绑定表和 `selection_only` 标记，不丢弃内容。缺少原始播放身份的旧手动记录
保留启发式恢复，直到删除或重新选择；新绑定过的内容（包括被替换的旧选择）不参与该回退。
此前因匹配失败无法恢复的选择，需要重新选择一次来建立绑定。

| mode | 含义 |
| --- | --- |
| `AUTO` (`auto`) | 高置信度自动候选，只服务所属 provider 的自动命中，不代表曾经显示 |
| `MANUAL` (`manual`) | 用户确认的结果，普通解析和 exact hint 都优先匹配 |

公开操作：

| 操作 | 用途 |
| --- | --- |
| `search(query)` | 按标题、艺术家、专辑、provider 或 song ID 模糊搜索，按最近访问排序 |
| `get(key)`、`count()` | 读取单条 metadata 或总数 |
| `upsert(artifact, mode)` | 创建或替换记录 |
| `select(track, artifact)` | 原子保存内容并替换该播放歌曲的手动绑定 |
| `update(key, artifact, mode)` | 更新已有记录，供歌词 workflow 使用；管理页面不提供编辑入口 |
| `delete(key)`、`delete_many(keys)`、`clear()` | 删除单条、批量删除或清空 |
| `lookup()`、`lookup_manual()` | resolver 专用的内容命中 |

缓存管理页面只使用 metadata search 和 delete/clear。它与 resolver 共享同一个 `LyricsCache`，但通过窄的 management/write port 接入，不依赖完整 MPRIS facade。

页面将保存方式显示为“自动缓存”或“手动选择”。“最近访问”在保存和匹配读取时更新，
包括最终没有胜出的候选，因此不是播放记录。独立状态区随当前显示内容更新歌词来源、获取方式、
播放来源和缓存状态。只有正在显示的 document 来自缓存，且 provider 与歌曲 ID 都一致时，
对应条目才标记“使用中”；实时歌词即使 ID 相同，也不会把缓存副本标记为已使用。

## 手动搜索和应用

悬浮窗的查找按钮打开 modeless 搜索窗口。标题和艺术家预填且可编辑。
专辑是可选条件，默认留空，即使播放器或当前歌词提供了专辑名也不自动填入，
避免不同发行版本的专辑名让 AMLL 等按专辑过滤的来源漏掉候选。
用户可手动填写专辑以缩小搜索范围；当前专辑和时长仍作为只读信息展示。

搜索服务并发查询已选 provider：每个 provider 最多返回 `30` 个候选，一次搜索最多向 UI 暴露 `90` 个结果，并按 `provider:provider_song_id` 去重。列表显示来源、标题、艺术家、专辑、时长、歌词格式、翻译可用性和匹配度。不可用 provider 以带 `source/reason` 的 typed result 返回。

应用候选时：

1. 原子地以 `MANUAL` mode 写入共享 cache，并绑定到原始播放 track。
2. 调用 `DisplayCoordinator.apply_manual_artifact()`。
3. 仅当当前播放 track 仍匹配搜索 track 时替换 document。
4. 立即按当前播放位置重新投影，播放中无需等待下一首。
5. 刷新搜索窗口的来源状态。

搜索窗口分别显示当前歌词 provider、获取方式、播放事实来源（MPRIS/Cider/adapter）和 cache 状态（未使用/自动 cache/手动选择）。切歌后手动 document 不覆盖新 track，新 track 按当前 source policy 重新解析。

## 本地来源和失败处理

sidecar 和 embedded 在 local worker 中读取，不写入 network cache，origin 分别为 `sidecar` 和 `embedded`。

`song.flac` 会读取相邻的 `song.ttml` 和 `song.lrc`，沿用普通文件、大小和同目录限制。
本地候选优先实际逐字时间；同等精度时 sidecar 优先于内嵌标签，TTML sidecar 优先于 LRC。
内嵌标签支持 TTML/LRC，需安装可选依赖 `mutagen`；一个 sidecar 无效不影响其他格式的读取。

provider 的 transport、解析和 payload 错误在边界处转换为窄 exception 或 typed unavailable result；cache 失败必须报告 `LyricsCacheError`，不能返回虚假成功。
