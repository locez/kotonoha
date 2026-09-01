# Kotonoha

[![CI](https://img.shields.io/github/actions/workflow/status/locez/kotonoha/test.yml?branch=main&label=CI)](https://github.com/locez/kotonoha/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/locez/kotonoha?display_name=tag&sort=semver)](https://github.com/locez/kotonoha/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://github.com/locez/kotonoha)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://github.com/locez/kotonoha/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-6f42c1)](https://github.com/locez/kotonoha/blob/main/LICENSE)

[中文](README.zh-CN.md)

Kotonoha is a Linux desktop lyrics overlay. It reads the current track and playback position from any MPRIS player, then shows synchronized lyrics in a translucent Wayland overlay.

It works with browsers, Spotify, VLC, mpv, Cider, and other MPRIS-compatible players. Lyrics can come from Netease, lrclib, Kugou, or Cider's local HTTP API.

![Kotonoha lyrics overlay](screenshots/kotonoha-screenshot.png)

> **Icon credit:** Special thanks to [Zakkaus](https://github.com/Zakkaus) for designing Kotonoha's icon.

## Features

- Any MPRIS player through D-Bus; no player-specific plugin is required.
- Word-by-word karaoke highlighting, translation, and smooth playback interpolation.
- Multiple lyric sources with configurable order, matching, fallback, and local cache.
- Manual lyric search and selection, with immediate application and persistent `MANUAL` cache entries.
- Local cache management with fuzzy metadata search, selective deletion, and full clearing.
- Wayland layer-shell overlay with click-through mode, dragging, translucency, and blur.
- Settings and system tray controls for fonts, colors, position, opacity, icons, and language.

Install the optional `mutagen` dependency to read LRC lyrics embedded in local audio tags.

## Installation

### Release packages

Download the latest artifacts from [GitHub Releases](https://github.com/locez/kotonoha/releases).

- Debian/Ubuntu: `sudo apt install ./kotonoha_*.deb`
- Fedora: `sudo dnf install ./kotonoha-*.rpm`
- Arch Linux: `paru -S kotonoha-git`

For Gentoo, enable the [gentoo-zh overlay](https://github.com/gentoo-zh/overlay):

```bash
sudo eselect repository enable gentoo-zh
sudo emaint sync
sudo emerge --ask media-plugins/kotonoha::gentoo-zh
```

NixOS users can add the package to a flake configuration:

```nix
inputs.kotonoha = {
  url = "github:locez/kotonoha";
  inputs.nixpkgs.follows = "nixpkgs";
};

environment.systemPackages = [
  inputs.kotonoha.packages.${pkgs.stdenv.hostPlatform.system}.default
];
```

Start the installed application with:

```bash
kotonoha
```

### Linux wheel

The release wheel is for Linux x86_64 and still needs compatible system Qt, Wayland, and LayerShellQt runtime libraries. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) first:

```bash
python3 -m venv .venv
uv pip install --python .venv/bin/python ./kotonoha-*-linux_x86_64.whl
.venv/bin/kotonoha
```

Python 3.13 or newer is what releases are checked against. 3.11 and 3.12 install and pass CI, but they are not guaranteed: a break that only affects them will not hold up a release.

### From source

Install the system dependencies first. `uv sync` then builds Kotonoha's native Wayland bridge automatically.

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

Then install and run Kotonoha:

```bash
git clone https://github.com/locez/kotonoha.git
cd kotonoha
uv sync
uv run kotonoha
```

## Before you start

- Floating above fullscreen requires a compositor that implements `wlr-layer-shell`, such as KDE/KWin or a wlroots-based compositor. GNOME/Mutter falls back to a normal top-most window.
- Frosted glass requires `ext-background-effect-v1` (KWin 6.7+, Mutter) or the older `org_kde_kwin_blur` (Plasma 6.6 and earlier). Without either, the panel stays translucent but unblurred and the frosted-glass options are greyed out.
- Browser players expose MPRIS through extensions such as [Plasma Browser Integration](https://github.com/KDE/plasma-browser-integration) and/or `playerctld`.

## Configuration

Open **Settings** from the tray. Under **Sources**, lyric providers can be reordered or disabled. The default order is `netease -> lrclib -> kugou -> cider`. The display sources below it can also have multiple enabled entries; their order controls which live player source wins when MPRIS is unavailable.

**Prefer best match** is enabled by default: cached results and matching Cider snapshots are considered first, then network sources compete by match quality. Disable it for strict ordered fallback.

The magnifying-glass button on the overlay opens manual lyric search for the current
track. Title, artist, and album are editable; the current duration is shown as
read-only context. Search results include provider, track metadata, duration, lyric
format, translation availability, and match confidence. Applying a result writes it
to the local cache as `MANUAL` and updates the visible lyrics immediately when the
same track is still playing. The search window also shows the active lyric provider,
acquisition path, playback source, and cache state.

**Local lyrics cache** in **Settings -> Sources** opens the cache manager. It searches
title, artist, album, provider, and provider song ID, and supports deleting selected
entries or clearing the cache. The manager intentionally does not edit lyric content;
manual replacement is performed through the current-track search flow.

Settings also controls fonts, colors, opacity, position, translation, icons, panel style, and lyric effects.

## Cider HTTP API (optional)

The current Cider integration uses Cider's local HTTP API directly; no Cider
plugin is required. Enable `cider` under **Settings -> Sources** when you want
it in the lyric source order.

Kotonoha fetches the complete timed lyric document once per track from Cider,
then calibrates playback position about once per second. The local media clock
interpolates between calibrations, so Cider is not polled for every display
frame.

If Cider API authentication is enabled, enter the token in **Settings ->
Sources -> Cider API token**. The token is optional and is persisted in
`config.json` with the rest of the settings. It is kept out of application logs.
When the field is empty, Kotonoha omits the `apptoken` header. External player
integrations use the generic `/kotonoha/adapter` snapshot/clock contract; see
[`plugins/README.md`](plugins/README.md) for the wire format and adaptation
boundary.

## Development checks

```bash
uv sync --locked --extra test --extra embedded-lyrics
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv run ruff check .
uv run ty check
uv build
```

## Documentation

- [Architecture](docs/SPEC.md)
- [Lyrics, cache, and manual selection](docs/SPEC-lyrics.md)
- [External adapter protocol](plugins/README.md)
