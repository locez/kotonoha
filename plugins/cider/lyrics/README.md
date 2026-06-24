# Kotonoha Cider Lyrics

Minimal Cider plugin for checking whether Cider can fetch Apple Music TTML lyrics in the background for Kotonoha's Linux desktop lyric overlay.

The probe does not mount or scrape Cider lyric views. It reads the current Apple Music song id, fetches `/syllable-lyrics` through `CiderApp.mkfetch`, parses TTML, and posts the current timed lyric line to the local receiver.

## Local Receiver

```bash
npm run receive
```

It listens on:

```text
http://127.0.0.1:28745/kotonoha/cider/lyrics
```

## Plugin Development

```bash
npm install
npm run dev
```

In Cider, enable plugin development/Vite loading for this plugin. The plugin POSTs snapshots to the local receiver once per second.

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
