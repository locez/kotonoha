# Kotonoha

[![CI](https://img.shields.io/github/actions/workflow/status/locez/kotonoha/test.yml?branch=main&label=CI)](https://github.com/locez/kotonoha/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/locez/kotonoha?display_name=tag&sort=semver)](https://github.com/locez/kotonoha/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://github.com/locez/kotonoha)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://github.com/locez/kotonoha/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-6f42c1)](https://github.com/locez/kotonoha/blob/main/LICENSE)

[English](README.md)

Kotonoha 是一个 Linux 桌面歌词悬浮窗。它从支持 MPRIS 的播放器读取当前歌曲和播放位置，并在半透明的 Wayland 悬浮层中显示同步歌词。

Kotonoha 支持浏览器、Spotify、VLC、mpv、Cider 以及其他兼容 MPRIS 的播放器。歌词可以来自 AMLL TTML DB、Netease、lrclib、Kugou 或 Cider 本地 HTTP API。

![Kotonoha lyrics overlay](screenshots/kotonoha-screenshot.png)

> **图标致谢：** 感谢 [Zakkaus](https://github.com/Zakkaus) 设计 Kotonoha 图标。

## 功能

- 通过 D-Bus 支持任意 MPRIS 播放器，不需要播放器专用插件。
- 逐字卡拉 OK 高亮、翻译和播放位置平滑插值。
- 多歌词来源、来源顺序、匹配策略、回退策略和本地缓存。
- 手动搜索和选择歌词，立即应用并持久化为 `MANUAL` 缓存条目。
- 本地歌词缓存管理，支持元数据模糊搜索、选择删除和清空缓存。
- Wayland Layer Shell 悬浮层，支持点击穿透、拖动、半透明和模糊。
- 托盘和设置窗口，支持字体、颜色、位置、不透明度、图标和语言配置。

安装可选的 `mutagen` 依赖后，可以读取本地音频标签中嵌入的 LRC 歌词。

## 安装

### Release 包

从 [GitHub Releases](https://github.com/locez/kotonoha/releases) 下载最新构建产物。

DEB、RPM 和 Linux wheel 均提供 x86_64 与 ARM64（aarch64）构建。DEB 文件名使用 `amd64` / `arm64`；RPM 和 wheel 文件名使用 `x86_64` / `aarch64`。

- Debian/Ubuntu：`sudo apt install ./kotonoha_*_"$(dpkg --print-architecture)".deb`
- Fedora：`sudo dnf install ./kotonoha-*."$(uname -m)".rpm`
- Arch Linux：`paru -S kotonoha-git`

DEB 和 RPM 包会在安装时使用本机 Qt 编译 `libkoto-layer.so`，并在相关 Qt 或
LayerShellQt 更新后重建。为此，包管理器会安装并保留 CMake、C++ 编译器和匹配的开发头文件；
安装过程中无需下载源码。构建错误会由包管理器报告，可运行
`sudo /usr/lib/kotonoha/rebuild-bridge` 手动重试。升级 Qt 后请重启 Kotonoha。
Linux wheel 仍携带预编译桥，需要兼容的 Qt 库。

如果本地构建失败，旧桥会保留；Qt 更新后它可能不再兼容，应用会在检测到版本不匹配时禁用桥。
首次安装没有可用桥时，同样会降级为普通窗口；这不表示 compositor 缺少 Layer Shell。
DEB 会保持未完成配置状态，修复构建错误后运行 `sudo dpkg --configure kotonoha`。
RPM 的安装后脚本失败不会回滚已安装的软件包或 Qt 更新；请修复错误后运行上面的重建命令。
编译输出直接显示在包管理器终端中。重建成功后请重启 Kotonoha。

Gentoo 用户可以启用 [gentoo-zh overlay](https://github.com/gentoo-zh/overlay)：

```bash
sudo eselect repository enable gentoo-zh
sudo emaint sync
sudo emerge --ask media-plugins/kotonoha::gentoo-zh
```

NixOS 用户可以在 flake 配置中添加：

```nix
inputs.kotonoha = {
  url = "github:locez/kotonoha";
  inputs.nixpkgs.follows = "nixpkgs";
};

environment.systemPackages = [
  inputs.kotonoha.packages.${pkgs.stdenv.hostPlatform.system}.default
];
```

启动已安装的程序：

```bash
kotonoha
```

### Linux wheel

Release wheel 面向 Linux x86_64 和 ARM64（aarch64），仍需要兼容的系统 Qt、Wayland 和 LayerShellQt 运行库。先安装 [`uv`](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
python3 -m venv .venv
uv pip install --python .venv/bin/python ./kotonoha-*-linux_"$(uname -m)".whl
.venv/bin/kotonoha
```

Release 会使用 Python 3.13 或更高版本进行检查。Python 3.11 和 3.12 可以安装并通过 CI，但不作为 Release 的保证范围。

### 从源码安装

先安装系统依赖。`uv sync` 会自动构建 Kotonoha 的原生 Wayland bridge。

```bash
# Arch
sudo pacman -S cmake qt6-base qt6-wayland layer-shell-qt

# Fedora
sudo dnf install cmake qt6-qtbase-devel qt6-qtbase-private-devel qt6-qtwayland-devel layer-shell-qt-devel wayland-devel gcc-c++

# Debian/Ubuntu
sudo apt install cmake build-essential pkg-config qt6-base-dev qt6-base-private-dev qt6-wayland-dev qt6-wayland-private-dev libwayland-dev liblayershellqtinterface-dev

# Gentoo
sudo emerge -a dev-build/cmake kde-plasma/layer-shell-qt dev-qt/qtwayland
```

然后安装并运行 Kotonoha：

```bash
git clone https://github.com/locez/kotonoha.git
cd kotonoha
uv sync
uv run kotonoha
```

## 使用条件

- 如果要悬浮在全屏窗口上方，需要实现 `wlr-layer-shell` 的 compositor，例如 KDE/KWin 或基于 wlroots 的 compositor。GNOME/Mutter 会回退到普通窗口，无法自动置顶。
- 在 GNOME/Mutter Wayland 中，右键解锁后的歌词可请求系统窗口菜单，再选择 **总在最前 / Always on Top**；窗口获得焦点时也可按 `Alt+Space`。菜单及堆叠由 Mutter 决定，不保证覆盖全屏应用或在窗口表面重建后保留置顶状态。
- 在 GNOME/Mutter Wayland 中，解锁后的悬浮窗会使用 compositor 的系统移动手势，因此不会发送客户端窗口移动请求，也不会保存客户端无法确认的坐标。
- 毛玻璃需要 `ext-background-effect-v1`（KWin 6.7+、Mutter）或旧版 `org_kde_kwin_blur`（Plasma 6.6 及更早版本）。两者都不可用时，面板仍保持半透明但不会模糊，毛玻璃选项会被禁用。
- 浏览器播放器可以通过 [Plasma Browser Integration](https://github.com/KDE/plasma-browser-integration) 和/或 `playerctld` 提供 MPRIS。

## 配置

从托盘打开**设置**。在**来源**页面可以调整或禁用歌词来源。默认顺序为 `amll -> netease -> lrclib -> kugou`。已有配置保留原来的来源选择，可在这里勾选 **AMLL TTML DB** 来启用新来源。下方的播放来源也可以启用多个条目；当 MPRIS 不可用时，列表顺序决定使用哪个实时播放器来源。

**优先最佳匹配**默认开启：依次比较歌曲匹配度、是否有可用的逐字时间信息、来源顺序。缓存、Cider 实时快照或播放器精确提示中的逐行歌词，可以被其他已启用来源中同等匹配度的逐字歌词替换。手动选择仍优先。关闭后使用严格的来源顺序回退。

[AMLL TTML DB](https://github.com/amll-dev/amll-ttml-db) 提供社区制作的 TTML，支持按歌名、歌手自动匹配和手动搜索，也能利用已知的平台歌曲 ID，不依赖特定播放器。新查询需要能访问其 GitHub 公共曲库；自动匹配成功或手动选中的歌词沿用本地缓存。收录范围取决于社区贡献，Cider 仍可补充当前 Apple Music 曲目的歌词。

播放本地音频时，将 `song.ttml` 或 `song.lrc` 放在 `song.flac`（或其他音频扩展名）旁边即可。TTML 支持逐行、逐字时间和内联翻译。本地文件及内嵌歌词优先选择逐字版本；同等时间精度的 sidecar 优先 TTML。读取内嵌标签需要安装 `embedded-lyrics` extra。其他网络接入分别读取网易云 YRC/LRC、酷狗 KRC/LRC、LRCLIB LRC、QQ 音乐 LRC；Cider 提供结构化时间轴歌词。

悬浮窗上的放大镜按钮会打开当前歌曲的手动搜索窗口。标题、艺术家和专辑可以编辑，当前时长以只读信息展示。搜索结果包含来源、歌曲元数据、时长、歌词格式、翻译可用性和匹配度。应用结果后会写入本地缓存并标记为 `MANUAL`；如果仍在播放同一首歌，显示歌词会立即更新。搜索窗口还会显示当前歌词来源、获取方式、播放来源和缓存状态。

**设置 -> 来源 -> 本地歌词缓存**打开缓存管理窗口。它支持按标题、艺术家、专辑、来源和来源歌曲 ID 模糊搜索，以及删除选中条目或清空缓存。管理窗口不直接编辑歌词内容；手动替换通过当前歌曲的手动搜索流程完成。

设置还可以调整字体、颜色、不透明度、位置、翻译、图标、面板样式和歌词效果。
“当前行发光”保留较宽的柔和外晕，并收轻贴近笔画的内晕，随演唱进度推进；文字每个区域只着色一次，保持字边清晰。“突出正在唱的字词”独立调整字词亮度，不叠加描边。两者都支持“轻微”和“明显”两档强度。

**设置 -> 歌词 -> 上下文行数（每侧）**默认上下一行，设为 0 时仅显示当前行，也可输入 10 行或更多。旧配置中的“仅显示当前播放行”会自动转换为上下文 0 行。远处的歌词逐渐缩小、变淡；**上下文模糊程度**默认 0%（关闭虚化），可调至 100%，开启后越远的行越模糊，隐藏上下文时保留所选强度。开启动画时相邻歌词平滑滚动；跨多行跳转和换歌立即就位。超出屏幕空间的行只在显示时裁切，不修改已保存的行数。

窗口不透明度、面板不透明度和上下文模糊程度均支持拖动滑条或输入精确百分比。普通面板和毛玻璃面板各自保留不透明度。点击**应用**使修改生效，**重置本页**恢复当前页默认值。

## Cider HTTP API（可选）

当前 Cider 集成直接使用 Cider 本地 HTTP API，不需要 Cider 专用插件。Cider 探测默认关闭；在**设置 -> 来源**的歌词来源列表中勾选 **Cider** 后才开始探测，并将它加入歌词来源顺序。已有配置中保存的来源选择会保留。

Kotonoha 每首歌从 Cider 获取一次完整的带时间轴歌词文档，然后大约每秒校准一次播放位置。显示帧之间使用本地媒体时钟插值，因此不会按每一帧轮询 Cider。

如果 Cider API 启用了认证，在**设置 -> 来源 -> Cider API token**中填写 token。token 是可选的，会和其他设置一起保存到 `config.json`，不会写入应用日志。字段为空时，Kotonoha 不发送 `apptoken` 请求头。外部播放器集成使用通用的 `/kotonoha/adapter` snapshot/clock 协议，详见 [`plugins/README.zh-CN.md`](plugins/README.zh-CN.md)。

## 开发检查

```bash
uv sync --locked --extra test --extra embedded-lyrics
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv run ruff check .
uv run ty check
uv build
```

## 文档

- [当前架构](docs/SPEC.zh-CN.md)
- [歌词、缓存和手动选词](docs/SPEC-lyrics.zh-CN.md)
- [外部适配器协议](plugins/README.zh-CN.md)

感谢 [amll-ttml-db](https://github.com/amll-dev/amll-ttml-db) 及其贡献者提供逐词歌词。
