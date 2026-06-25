# Kotonoha

Kotonoha is a Linux desktop lyrics overlay experiment using the same core stack as BiliHUD: Python, PyQt6, qasync, and local player bridge plugins.

The first plugin target is Cider. Its probe plugin lives at:

```text
plugins/cider/lyrics
```

That plugin fetches Apple Music TTML lyrics through Cider's `CiderApp.mkfetch` and streams the current lyric context to Kotonoha over a local WebSocket. It does not scrape or mount Cider lyric views.

## Features

- Frameless, translucent, top-most lyrics overlay.
- Floats above fullscreen apps on Wayland via `wlr-layer-shell` (layer-shell-qt bridge).
- Per-word karaoke sweep (Apple Music word timing) with a pink accent and an optional translation line.
- Click-through by default — the overlay never blocks your clicks; toggle it off from the tray to reposition.
- Event-driven WebSocket transport: line changes show near-instantly; a local 60fps clock keeps the sweep smooth between updates.

See [`docs/SPEC.md`](docs/SPEC.md) for the full design.

## Layout

```text
src/kotonoha/                 Python overlay application
  layer_shell_bridge.cpp      Wayland layer-shell bridge (compiled to libkoto-layer.so)
  receiver.py                 aiohttp WebSocket server (ingests probe frames)
  overlay.py / karaoke_label  Translucent overlay window + word-sweep renderer
plugins/cider/lyrics/         Cider TTML lyrics probe (WebSocket client)
```

## System dependencies

The overlay needs Qt6 + layer-shell-qt to build the Wayland bridge:

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

> Wayland overlay-above-fullscreen requires a compositor that implements `wlr-layer-shell`
> (KDE Plasma/KWin, wlroots-based). GNOME/Mutter does not — Kotonoha falls back to a normal
> top-most window there.

## Python App

```bash
uv sync
uv run kotonoha
```

The overlay starts a WebSocket receiver on `ws://127.0.0.1:28745/kotonoha/cider/lyrics` and shows
a tray icon. Run the Cider probe (below) and start playing a song with synced lyrics.

## Cider Probe

```bash
cd plugins/cider/lyrics
npm install
npm run build
npm run receive
```

Copy the built plugin directory into Cider's plugin directory:

```bash
rm -rf ~/.config/sh.cider.genten/plugins/dev.locez.kotonoha.cider.lyrics
cp -r dist/dev.locez.kotonoha.cider.lyrics ~/.config/sh.cider.genten/plugins/
```
