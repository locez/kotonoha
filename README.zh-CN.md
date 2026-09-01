# Kotonoha

[![CI](https://img.shields.io/github/actions/workflow/status/locez/kotonoha/test.yml?branch=main&label=CI)](https://github.com/locez/kotonoha/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/locez/kotonoha?display_name=tag&sort=semver)](https://github.com/locez/kotonoha/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://github.com/locez/kotonoha)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://github.com/locez/kotonoha/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-6f42c1)](https://github.com/locez/kotonoha/blob/main/LICENSE)

[English](README.md)

Kotonoha 是一个 Linux 桌面歌词悬浮窗。它从支持 MPRIS 的播放器读取当前歌曲和播放位置，并在半透明的 Wayland 悬浮层中显示同步歌词。

Kotonoha 支持浏览器、Spotify、VLC、mpv、Cider 以及其他兼容 MPRIS 的播放器。歌词可以来自 Netease、lrclib、Kugou 或 Cider 本地 HTTP API。

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

- Debian/Ubuntu：`sudo apt install ./kotonoha_*.deb`
- Fedora：`sudo dnf install ./kotonoha-*.rpm`
- Arch Linux：`paru -S kotonoha-git`

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

Release wheel 面向 Linux x86_64，仍需要兼容的系统 Qt、Wayland 和 LayerShellQt 运行库。先安装 [`uv`](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
python3 -m venv .venv
uv pip install --python .venv/bin/python ./kotonoha-*-linux_x86_64.whl
.venv/bin/kotonoha
```

Release 会使用 Python 3.13 或更高版本进行检查。Python 3.11 和 3.12 可以安装并通过 CI，但不作为 Release 的保证范围。

### 从源码安装

先安装系统依赖。`uv sync` 会自动构建 Kotonoha 的原生 Wayland bridge。

```bash
# Arch
sudo pacman -S cmake qt6-base qt6-wayland layer-shell-qt

# Fedora
sudo dnf install cmake qt6-qtbase-devel layer-shell-qt-devel wayland-devel gcc-c++

# Debian/Ubuntu
sudo apt install cmake build-essential pkg-config qt6-base-dev qt6-base-private-dev qt6-wayland-dev libwayland-dev liblayershellqtinterface-dev

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

- 如果要悬浮在全屏窗口上方，需要实现 `wlr-layer-shell` 的 compositor，例如 KDE/KWin 或基于 wlroots 的 compositor。GNOME/Mutter 会回退到普通的置顶窗口。
- 毛玻璃需要 `ext-background-effect-v1`（KWin 6.7+、Mutter）或旧版 `org_kde_kwin_blur`（Plasma 6.6 及更早版本）。两者都不可用时，面板仍保持半透明但不会模糊，毛玻璃选项会被禁用。
- 浏览器播放器可以通过 [Plasma Browser Integration](https://github.com/KDE/plasma-browser-integration) 和/或 `playerctld` 提供 MPRIS。

## 配置

从托盘打开**设置**。在**来源**页面可以调整或禁用歌词来源。默认顺序为 `netease -> lrclib -> kugou -> cider`。下方的播放来源也可以启用多个条目；当 MPRIS 不可用时，列表顺序决定使用哪个实时播放器来源。

**优先最佳匹配**默认开启：先考虑缓存结果和 Cider 实时快照，再让网络来源按匹配质量竞争。关闭后使用严格的来源顺序回退。

悬浮窗上的放大镜按钮会打开当前歌曲的手动搜索窗口。标题、艺术家和专辑可以编辑，当前时长以只读信息展示。搜索结果包含来源、歌曲元数据、时长、歌词格式、翻译可用性和匹配度。应用结果后会写入本地缓存并标记为 `MANUAL`；如果仍在播放同一首歌，显示歌词会立即更新。搜索窗口还会显示当前歌词来源、获取方式、播放来源和缓存状态。

**设置 -> 来源 -> 本地歌词缓存**打开缓存管理窗口。它支持按标题、艺术家、专辑、来源和来源歌曲 ID 模糊搜索，以及删除选中条目或清空缓存。管理窗口不直接编辑歌词内容；手动替换通过当前歌曲的手动搜索流程完成。

设置还可以调整字体、颜色、不透明度、位置、翻译、图标、面板样式和歌词效果。

## Cider HTTP API（可选）

当前 Cider 集成直接使用 Cider 本地 HTTP API，不需要 Cider 专用插件。在**设置 -> 来源**中启用 `cider`，即可将它加入歌词来源顺序。

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
