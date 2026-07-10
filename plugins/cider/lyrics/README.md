# Kotonoha Cider Lyrics

Optional Cider plugin that supplies Apple Music TTML lyrics and reliable playback metadata to Kotonoha's Linux desktop lyric overlay.

> **Experimental:** The current Cider 4 player layout and MusicKit clock are supported, but this plugin still depends on Cider internals and Apple Music's private TTML response. Keep Netease or lrclib enabled as external providers.

The probe does not mount or scrape Cider lyric views. It reads the current Apple Music song ID, fetches `/syllable-lyrics` through `CiderApp.mkfetch`, parses TTML, and streams the current timed lyric line to the local receiver over WebSocket. Playback state is read from the current Cider player layout with MusicKit fallbacks for song-relative time, duration, playing state, and now-playing metadata.

It connects as a WebSocket client with automatic reconnect/backoff, pushes a full snapshot on connect and track/line changes, sends a heartbeat about once per second, and sends lightweight clock ticks about every 100 ms.

## Local Receiver

`pnpm receive` starts a standalone WebSocket debug receiver when Kotonoha itself is not running:

```bash
pnpm receive
```

It listens on:

```text
ws://127.0.0.1:28745/kotonoha/cider/lyrics
```

Kotonoha's Python app hosts the same WebSocket endpoint, so in normal use you do not run this — just start `kotonoha`.

## Plugin Development

```bash
pnpm install
pnpm dev
```

In Cider, enable plugin development/Vite loading for this plugin. The plugin streams full snapshots and lightweight playback ticks to the local receiver.

## Build

```bash
pnpm test
pnpm build
```

The built plugin goes to:

```text
dist/dev.locez.kotonoha.cider.lyrics/plugin.js
```

For a manual install or update on Linux:

```bash
install -d ~/.config/sh.cider.genten/plugins/dev.locez.kotonoha.cider.lyrics
cp dist/dev.locez.kotonoha.cider.lyrics/plugin.js \
  ~/.config/sh.cider.genten/plugins/dev.locez.kotonoha.cider.lyrics/plugin.js
cp dist/dev.locez.kotonoha.cider.lyrics/plugin.yml \
  ~/.config/sh.cider.genten/plugins/dev.locez.kotonoha.cider.lyrics/plugin.yml
```

Reload Cider after copying. Repeat the build, copy, and reload steps after changing plugin source code.
