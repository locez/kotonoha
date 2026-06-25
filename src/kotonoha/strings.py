"""UI internationalization (menus, settings).

A lightweight string table keyed by a stable id, with simplified Chinese,
traditional Chinese, Japanese and English. The active language follows the
config (``ui_language``, default "auto" -> system locale). Call ``set_language``
once at startup, then ``t(key)`` everywhere a UI string is needed.
"""

from __future__ import annotations

from .i18n import normalize_to_apple_tag, system_translation_language

# (value, display label) for the settings picker.
UI_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("auto", "跟随系统 / Auto"),
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("ja", "日本語"),
    ("en", "English"),
)

_SUPPORTED = ("en", "zh-Hans", "zh-Hant", "ja")
_FALLBACK = "en"
_current = _FALLBACK

# key -> {lang: text}. English is the fallback for any missing entry.
STRINGS: dict[str, dict[str, str]] = {
    "tray.tooltip": {"en": "Kotonoha — lyrics overlay", "zh-Hans": "Kotonoha — 歌词浮窗",
                     "zh-Hant": "Kotonoha — 歌詞浮窗", "ja": "Kotonoha — 歌詞オーバーレイ"},
    "tray.lock": {"en": "Lock / click-through", "zh-Hans": "锁定 / 鼠标穿透",
                  "zh-Hant": "鎖定 / 滑鼠穿透", "ja": "ロック / クリック透過"},
    "tray.settings": {"en": "Settings…", "zh-Hans": "设置…", "zh-Hant": "設定…", "ja": "設定…"},
    "tray.quit": {"en": "Quit", "zh-Hans": "退出", "zh-Hant": "結束", "ja": "終了"},

    "overlay.locked": {"en": "Locked (click-through) — click to unlock & drag",
                       "zh-Hans": "已锁定（鼠标穿透）— 点击解锁可拖动",
                       "zh-Hant": "已鎖定（滑鼠穿透）— 點擊解鎖可拖動",
                       "ja": "ロック中（クリック透過）— クリックで解除して移動"},
    "overlay.unlocked": {"en": "Unlocked (draggable) — click to lock & pass through",
                         "zh-Hans": "已解锁（可拖动）— 点击锁定并穿透",
                         "zh-Hant": "已解鎖（可拖動）— 點擊鎖定並穿透",
                         "ja": "解除中（移動可）— クリックでロックして透過"},
    "overlay.settings": {"en": "Settings", "zh-Hans": "设置", "zh-Hant": "設定", "ja": "設定"},

    "settings.title": {"en": "Kotonoha Settings", "zh-Hans": "Kotonoha 设置",
                       "zh-Hant": "Kotonoha 設定", "ja": "Kotonoha 設定"},
    "tab.appearance": {"en": "Appearance", "zh-Hans": "外观", "zh-Hant": "外觀", "ja": "外観"},
    "tab.lyrics": {"en": "Lyrics", "zh-Hans": "歌词", "zh-Hant": "歌詞", "ja": "歌詞"},
    "tab.position": {"en": "Position", "zh-Hans": "位置", "zh-Hant": "位置", "ja": "位置"},
    "tab.sources": {"en": "Sources", "zh-Hans": "来源", "zh-Hant": "來源", "ja": "ソース"},
    "tab.connection": {"en": "Connection", "zh-Hans": "连接", "zh-Hant": "連接", "ja": "接続"},
    "tab.general": {"en": "General", "zh-Hans": "通用", "zh-Hant": "通用", "ja": "一般"},

    "set.font_size": {"en": "Current line size", "zh-Hans": "当前行字号",
                      "zh-Hant": "當前行字級", "ja": "現在行のサイズ"},
    "set.opacity": {"en": "Opacity", "zh-Hans": "不透明度", "zh-Hant": "不透明度", "ja": "不透明度"},
    "set.panel_style": {"en": "Panel style", "zh-Hans": "背板样式", "zh-Hant": "背板樣式", "ja": "パネル様式"},
    "set.panel.pill": {"en": "Glass panel", "zh-Hans": "玻璃面板", "zh-Hant": "玻璃面板", "ja": "グラスパネル"},
    "set.panel.text": {"en": "Text only", "zh-Hans": "纯文字", "zh-Hant": "純文字", "ja": "テキストのみ"},
    "set.accent": {"en": "Accent color", "zh-Hans": "强调色", "zh-Hant": "強調色", "ja": "アクセント色"},
    "set.accent.custom": {"en": "Custom", "zh-Hans": "自定义", "zh-Hant": "自訂", "ja": "カスタム"},
    "set.karaoke": {"en": "Word-by-word highlight", "zh-Hans": "逐字高亮",
                    "zh-Hant": "逐字高亮", "ja": "文字単位ハイライト"},
    "set.lead": {"en": "Lyric lead", "zh-Hans": "歌词提前", "zh-Hant": "歌詞提前", "ja": "歌詞の先行"},
    "set.lead.tip": {"en": "Positive advances the highlight (compensates latency), negative delays it",
                     "zh-Hans": "正值让染色提前（补偿延迟），负值让染色滞后",
                     "zh-Hant": "正值讓染色提前（補償延遲），負值讓染色滯後",
                     "ja": "正の値でハイライトを早め（遅延補正）、負で遅らせる"},
    "set.show_translation": {"en": "Show translation", "zh-Hans": "显示翻译",
                             "zh-Hant": "顯示翻譯", "ja": "翻訳を表示"},
    "set.position": {"en": "Edge", "zh-Hans": "位置", "zh-Hant": "位置", "ja": "位置"},
    "set.top": {"en": "Top", "zh-Hans": "顶部", "zh-Hant": "頂部", "ja": "上"},
    "set.bottom": {"en": "Bottom", "zh-Hans": "底部", "zh-Hant": "底部", "ja": "下"},
    "set.margin_edge": {"en": "Distance from edge", "zh-Hans": "距边缘",
                        "zh-Hant": "距邊緣", "ja": "端からの距離"},
    "set.margin_x": {"en": "Horizontal offset", "zh-Hans": "水平偏移",
                     "zh-Hant": "水平偏移", "ja": "水平オフセット"},
    "set.passthrough": {"en": "Click-through by default (locked)", "zh-Hans": "默认鼠标穿透（锁定）",
                        "zh-Hant": "預設滑鼠穿透（鎖定）", "ja": "既定でクリック透過（ロック）"},
    "set.box_hint": {
        "en": "The overlay is a fixed-size transparent box (~90% screen width) with centered text — "
              "not auto-fit — for stable Wayland layer-shell display. Unlock to drag the whole box.",
        "zh-Hans": "浮窗是一个固定大小的透明框（约屏宽 90%），歌词在框内居中，并非自适应——"
                   "这是为了在 Wayland layer-shell 下稳定显示。解锁后整个透明框都可拖动。",
        "zh-Hant": "浮窗是一個固定大小的透明框（約螢幕寬 90%），歌詞置中，並非自適應——"
                   "這是為了在 Wayland layer-shell 下穩定顯示。解鎖後整個透明框都可拖動。",
        "ja": "オーバーレイは固定サイズの透明ボックス（画面幅の約90%）でテキストを中央に表示します。"
              "Wayland layer-shell で安定表示するため自動調整ではありません。解除すると全体を移動できます。",
    },
    "set.sources_hint": {
        "en": "Lyric source priority: top to bottom, the first one with lyrics wins. "
              "Drag to reorder, uncheck to disable.",
        "zh-Hans": "歌词来源优先级：从上到下，第一个有歌词的就用它。拖动排序，取消勾选即禁用。",
        "zh-Hant": "歌詞來源優先級：從上到下，第一個有歌詞的就用它。拖動排序，取消勾選即停用。",
        "ja": "歌詞ソースの優先順位：上から順に、最初に歌詞が見つかったものを使用。"
              "ドラッグで並べ替え、チェックを外すと無効。",
    },
    "src.netease": {"en": "Netease", "zh-Hans": "网易云", "zh-Hant": "網易雲", "ja": "网易云"},
    "src.lrclib": {"en": "lrclib", "zh-Hans": "lrclib", "zh-Hant": "lrclib", "ja": "lrclib"},
    "src.cider": {"en": "Cider", "zh-Hans": "Cider 自带", "zh-Hant": "Cider 自帶", "ja": "Cider 内蔵"},
    "set.port": {"en": "WebSocket port", "zh-Hans": "WebSocket 端口",
                 "zh-Hant": "WebSocket 連接埠", "ja": "WebSocket ポート"},
    "set.port_hint": {
        "en": "Changing the port needs a restart and a matching change to the Cider probe endpoint.",
        "zh-Hans": "修改端口需重启 Kotonoha 生效，并同步修改 Cider 探针的 endpoint。",
        "zh-Hant": "修改連接埠需重啟 Kotonoha 生效，並同步修改 Cider 探針的 endpoint。",
        "ja": "ポート変更は再起動が必要で、Cider プローブの endpoint も合わせて変更してください。",
    },
    "set.language": {"en": "Language", "zh-Hans": "语言", "zh-Hant": "語言", "ja": "言語"},
    "set.language_hint": {"en": "Takes effect after restart.", "zh-Hans": "重启后生效。",
                          "zh-Hant": "重啟後生效。", "ja": "再起動後に反映されます。"},
}


def resolve_ui_language(value: str | None) -> str:
    if not value or value == "auto":
        lang = system_translation_language()
    else:
        lang = normalize_to_apple_tag(value)
    return lang if lang in _SUPPORTED else _FALLBACK


def set_language(value: str | None) -> None:
    global _current
    _current = resolve_ui_language(value)


def current_language() -> str:
    return _current


def t(key: str) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(_current) or entry.get(_FALLBACK) or key
