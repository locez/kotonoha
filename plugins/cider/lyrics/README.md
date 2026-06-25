# Kotonoha Cider Lyrics

Minimal Cider plugin for checking whether Cider can fetch Apple Music TTML lyrics in the background for Kotonoha's Linux desktop lyric overlay.

The probe does not mount or scrape Cider lyric views. It reads the current Apple Music song id, fetches `/syllable-lyrics` through `CiderApp.mkfetch`, parses TTML, and streams the current timed lyric line to the local receiver over WebSocket.

It connects as a WebSocket client (with automatic reconnect/backoff), pushes a full snapshot on connect, sends a frame on every change (line/play-pause/seek/track), and a low-frequency heartbeat for clock-drift correction.

## Local Receiver

`npm run receive` starts a standalone WebSocket debug receiver (handy when Kotonoha itself is not running):

```bash
npm run receive
```

It listens on:

```text
ws://127.0.0.1:28745/kotonoha/cider/lyrics
```

Kotonoha's Python app hosts the same WebSocket endpoint, so in normal use you do not run this — just start `kotonoha`.

## Plugin Development

```bash
npm install
npm run dev
```

In Cider, enable plugin development/Vite loading for this plugin. The plugin streams snapshots to the local receiver over WebSocket (event-driven, plus a ~1s heartbeat).

## Build

```bash
npm run build
```

The built plugin goes to:

```text
dist/dev.locez.kotonoha.cider.lyrics/plugin.js
```

For a manual install on Linux, copy the built plugin directory into:

```text
~/.config/sh.cider.genten/plugins
```
