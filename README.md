# Kotonoha

Kotonoha is a Linux desktop **lyrics overlay**: a translucent, click-through, top-most window that floats above fullscreen apps on Wayland and shows word-by-word synced lyrics for whatever you're playing.

It works with **any MPRIS player** (browser YouTube Music, Spotify, VLC, mpv, Cider, …): it reads the now-playing track + progress over D-Bus, then fetches timed lyrics from **Netease** (word-timed + Chinese translation, no login) → **lrclib** → optionally the **Cider** plugin's Apple Music lyrics — first source that has the song wins, and you can reorder them.

Built on the same core stack as BiliHUD: Python, PyQt6, qasync, and a `layer-shell-qt` bridge.

## Features

- **Any MPRIS player** via D-Bus — no per-player plugin required.
- **Word-by-word karaoke sweep** with a synced translation line and a pink accent.
- **Multi-source timed lyrics**, user-ordered priority (Settings → 来源): Netease (word-level YRC) / lrclib / Cider (Apple Music).
- **Provider-local persistent cache**: each network source checks its own validated local artifacts first; cache can be disabled or cleared.
- Floats above fullscreen on Wayland via `wlr-layer-shell`; translucent, **click-through** by default, **lock-to-immersive** (text only), draggable.
- Smooth: a local 60fps clock interpolates between ~100ms progress samples; adjustable lead offset.
- Tabbed settings panel + system tray.

Design docs: [`docs/SPEC.md`](docs/SPEC.md) (overlay) and [`docs/SPEC-mpris-lyrics.md`](docs/SPEC-mpris-lyrics.md) (MPRIS + lyrics).

## System dependencies

`uv sync` **compiles a small C++ Wayland bridge** (`libkoto-layer.so`) automatically via a
hatch build hook (`build_bridge.sh`) — there's nothing to build by hand. But it needs Qt6 +
layer-shell-qt installed first, otherwise the sync fails and prints exactly what to install:

```bash
# Arch
sudo pacman -S qt6-base qt6-wayland layer-shell-qt
# Fedora
sudo dnf install qt6-qtbase-devel layer-shell-qt-devel wayland-devel gcc-c++
# Debian/Ubuntu
sudo apt install qt6-base-dev qt6-base-private-dev libwayland-dev liblayershellqt-dev build-essential
# Gentoo
sudo emerge -a kde-plasma/layer-shell-qt dev-qt/qtwayland
```

> Floating above fullscreen needs a compositor that implements `wlr-layer-shell`
> (KDE Plasma/KWin, wlroots-based). GNOME/Mutter does not — Kotonoha falls back to a
> normal top-most window there.
>
> Browser players (YouTube Music) reach MPRIS via the **Plasma Browser Integration**
> extension and/or `playerctld`.

## Run

```bash
uv sync                  # also compiles the layer-shell bridge (needs the deps above)
uv run kotonoha          # add -v for verbose logs
```

> The bridge is built automatically by `uv sync`. If you edit the C++
> (`src/kotonoha/layer_shell_bridge.cpp`), rebuild it directly with
> `bash src/kotonoha/build_bridge.sh`.

Then just play something in any MPRIS player. Kotonoha shows a tray icon; left-click it to lock/unlock the overlay, right-click for Settings.

**Lyric source priority** is in Settings → **来源**: drag to reorder, uncheck to disable. Default order is `netease → lrclib → cider`.

With the local cache enabled, that default order is resolved exactly as:

1. local Netease cache
2. network Netease
3. local lrclib cache
4. network lrclib
5. the current matching Cider live snapshot, when available

Reordering a provider moves its cache and network stages together. Cider is attempted at its configured position; it is not automatically preferred just because the active MPRIS player is Cider. Cache entries are stored by the provider's stable song ID and matched against the current playback metadata at lookup time.

## Cider probe (experimental, optional)

> **Experimental:** The Cider probe depends on Cider's internal plugin APIs and Apple Music's TTML response. It may break after Cider updates or produce missing, incomplete, or delayed snapshots. Use it cautiously and keep external lyric providers enabled.

The Cider plugin adds Apple Music's own TTML lyrics to the configured priority list. It is not required for MPRIS playback or external providers. Built with Vite + pnpm:

```bash
cd plugins/cider/lyrics
pnpm install
pnpm build
```

Copy the built plugin into Cider's plugin directory:

```bash
rm -rf ~/.config/sh.cider.genten/plugins/dev.locez.kotonoha.cider.lyrics
cp -r dist/dev.locez.kotonoha.cider.lyrics ~/.config/sh.cider.genten/plugins/
```

The plugin connects to Kotonoha over WebSocket (`ws://127.0.0.1:28745/kotonoha/cider/lyrics`) and pushes Apple Music lyric snapshots + playback ticks. Kotonoha retains the latest snapshot while external providers are being tried and only lets the selected connection drive content and time. `pnpm receive` runs a standalone debug receiver; `pnpm test` runs the unit tests.

During an MPRIS track transition, empty or partially updated metadata is held briefly instead of being searched immediately. A player that cannot expose `Position` can still resolve lyrics, although synchronized progression then depends on that player eventually providing usable progress.

## Layout

```text
src/kotonoha/                 Python overlay application
  providers/mpris.py          MPRIS provider (dbus-fast): track + progress
  lyrics/                     Provider resolver, cache, Netease/lrclib, parsers, matching
  layer_shell_bridge.cpp      Wayland layer-shell bridge (-> libkoto-layer.so)
  overlay.py / karaoke_label  Translucent overlay + word-sweep renderer
  receiver.py                 aiohttp WebSocket server (Cider probe frames)
plugins/cider/lyrics/         Optional Cider Apple Music probe (WebSocket client)
```
