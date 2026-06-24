# Kotonoha

Kotonoha is a Linux desktop lyrics overlay experiment using the same core stack as BiliHUD: Python, PyQt6, qasync, and local player bridge plugins.

The first plugin target is Cider. Its probe plugin lives at:

```text
plugins/cider/lyrics
```

That plugin fetches Apple Music TTML lyrics through Cider's `CiderApp.mkfetch` and posts the current lyric context to a local receiver. It does not scrape or mount Cider lyric views.

## Layout

```text
src/kotonoha/                 Python overlay application
plugins/cider/                Cider-specific plugin projects
plugins/cider/lyrics/
                              Current Cider TTML lyrics probe
```

## Python App

```bash
uv sync
uv run kotonoha
```

The Python app is currently a minimal placeholder. The next step is to add the local lyrics receiver and PyQt6 overlay window.

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
