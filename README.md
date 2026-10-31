# Kotonoha

[![CI](https://img.shields.io/github/actions/workflow/status/locez/kotonoha/test.yml?branch=main&label=CI)](https://github.com/locez/kotonoha/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/locez/kotonoha?display_name=tag&sort=semver)](https://github.com/locez/kotonoha/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://github.com/locez/kotonoha)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://github.com/locez/kotonoha/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-6f42c1)](https://github.com/locez/kotonoha/blob/main/LICENSE)

[中文](README.zh-CN.md)

Kotonoha is a Linux desktop lyrics overlay. It reads the current track and playback position from any MPRIS player, then shows synchronized lyrics in a translucent Wayland overlay.

It works with browsers, Spotify, VLC, mpv, Cider, and other MPRIS-compatible players. Lyrics can come from AMLL TTML DB, Netease, lrclib, Kugou, or Cider's local HTTP API.

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

DEB, RPM, and Linux wheel packages are built for x86_64 and ARM64 (aarch64). DEB filenames use `amd64` / `arm64`; RPM and wheel filenames use `x86_64` / `aarch64`.

- Debian/Ubuntu: `sudo apt install ./kotonoha_*_"$(dpkg --print-architecture)".deb`
- Fedora: `sudo dnf install ./kotonoha-*."$(uname -m)".rpm`
- Arch Linux: `paru -S kotonoha-git`

DEB and RPM packages compile `libkoto-layer.so` against your system Qt during
installation and rebuild it after relevant Qt or LayerShellQt updates. The package
manager installs and retains CMake, a C++ compiler, and the matching development
headers for this purpose; installation requires no source downloads. Build errors
are reported by the package manager. To retry manually, run
`sudo /usr/lib/kotonoha/rebuild-bridge`. Restart Kotonoha after upgrading Qt.
Linux wheels still contain a prebuilt bridge and require compatible Qt libraries.

If compilation fails, the previous bridge is preserved. It may be incompatible
after a Qt update; the application disables the bridge when its version check
fails. A first install without a bridge also falls back to an ordinary window;
this does not mean the compositor lacks Layer Shell. DEB remains unconfigured:
fix the build error and run `sudo dpkg --configure kotonoha`. An RPM post-install
failure does not roll back the installed package or Qt update: fix the error and
retry the rebuild command above. Compiler output appears in the package manager's
terminal. Restart Kotonoha after a successful rebuild.

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

The release wheels are for Linux x86_64 and ARM64 (aarch64) and still need compatible system Qt, Wayland, and LayerShellQt runtime libraries. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) first:

```bash
python3 -m venv .venv
uv pip install --python .venv/bin/python ./kotonoha-*-linux_"$(uname -m)".whl
.venv/bin/kotonoha
```

Python 3.13 or newer is what releases are checked against. 3.11 and 3.12 install and pass CI, but they are not guaranteed: a break that only affects them will not hold up a release.

### From source

Install the system dependencies first. `uv sync` then builds Kotonoha's native Wayland bridge automatically.

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

Then install and run Kotonoha:

```bash
git clone https://github.com/locez/kotonoha.git
cd kotonoha
uv sync
uv run kotonoha
```

## Before you start

- Floating above fullscreen requires a compositor that implements `wlr-layer-shell`, such as KDE/KWin or a wlroots-based compositor. GNOME/Mutter falls back to an ordinary window; automatic top-most stacking is unavailable.
- On GNOME/Mutter Wayland, right-click the unlocked lyrics to request the system window menu and select **Always on Top**. `Alt+Space` also opens this menu when the window has focus. Mutter controls menu availability and stacking; this does not guarantee placement above fullscreen apps or persistence after surface recreation.
- On GNOME/Mutter Wayland, an unlocked overlay uses the compositor's system move gesture, so dragging does not send client-side window moves or save coordinates that the client cannot verify.
- Frosted glass requires `ext-background-effect-v1` (KWin 6.7+, Mutter) or the older `org_kde_kwin_blur` (Plasma 6.6 and earlier). Without either, the panel stays translucent but unblurred and the frosted-glass options are greyed out.
- Browser players expose MPRIS through extensions such as [Plasma Browser Integration](https://github.com/KDE/plasma-browser-integration) and/or `playerctld`.

## Configuration

Open **Settings** from the tray. Under **Sources**, lyric providers can be reordered or disabled. The default order is `amll -> netease -> lrclib -> kugou`. Existing saved selections are preserved; enable **AMLL TTML DB** there to add it to an existing configuration. The display sources below it can also have multiple enabled entries; their order controls which live player source wins when MPRIS is unavailable.

**Prefer best match** is enabled by default: candidates compete by match confidence, then usable word timing, then your source order. A line-timed cache hit, Cider snapshot, or exact player hint can be upgraded by equally well-matched word lyrics from another enabled source. Manual selections remain authoritative. Disable it for strict ordered fallback.

[AMLL TTML DB](https://github.com/amll-dev/amll-ttml-db) supplies community-authored TTML for automatic matching and manual search by song title and artist, independently of the player. It can also use known platform song IDs. New lookups require access to its public GitHub catalog; successfully matched or manually selected lyrics use the existing local cache. Coverage depends on community submissions. Cider remains useful for lyrics supplied by its active Apple Music track.

For local audio, place `song.ttml` or `song.lrc` beside `song.flac` (or another audio extension). TTML supports line and word timing plus inline translations. Local files and embedded lyric tags prefer word timing; TTML wins a sidecar format tie. Embedded tags require the `embedded-lyrics` extra. Other network integrations provide NetEase YRC/LRC, Kugou KRC/LRC, LRCLIB LRC, and QQ Music LRC; Cider supplies structured timed lyrics.

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
The active-line glow uses a restrained inner halo and a wider bloom behind the sung portion, with a feathered progress edge.
Each foreground region is colored once to keep the glyph edges crisp. Current-word highlighting brightens the word without
adding an outline. Both effects offer subtle and expressive intensity settings.
**Context lines on each side** in **Settings -> Lyrics** defaults to one. Set it to zero
to show only the current line, or enter larger counts, including ten or more. Older
**Show current line only** settings are automatically converted to zero context lines.
Farther rows become smaller, dimmer, and more blurred. **Context blur** adjusts the
strength from 0% (no blur) to 100%, with a gentle 25% default. It retains its value while
context is hidden. Adjacent line changes scroll smoothly when animations are enabled;
jumps across multiple lines and track changes settle immediately. The viewport clips
rows that exceed the screen space without changing the saved count.

Window opacity, panel opacity, and context blur use sliders with percentage inputs for
precise edits. The regular and frosted panels retain independent opacity values. Click
**Apply** to use your changes; **Reset tab** restores that page's defaults.

## Cider HTTP API (optional)

The current Cider integration uses Cider's local HTTP API directly; no Cider
plugin is required. Cider probing is disabled by default. Enable **Cider** in
the lyric sources list under **Settings -> Sources** to start probing and add
it to the lyric source order. Existing saved source selections are preserved.

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

Thanks to [amll-ttml-db](https://github.com/amll-dev/amll-ttml-db) and its contributors for the word-timed lyrics.
