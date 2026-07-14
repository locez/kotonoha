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
    "overlay.idle": {"en": "♪ Waiting for music…", "zh-Hans": "♪ 等待音乐…",
                     "zh-Hant": "♪ 等待音樂…", "ja": "♪ 音楽を待っています…"},

    "settings.title": {"en": "Kotonoha Settings", "zh-Hans": "Kotonoha 设置",
                       "zh-Hant": "Kotonoha 設定", "ja": "Kotonoha 設定"},
    "tab.text": {"en": "Text", "zh-Hans": "文字", "zh-Hant": "文字", "ja": "テキスト"},
    "tab.panel": {"en": "Panel", "zh-Hans": "面板", "zh-Hant": "面板", "ja": "パネル"},
    "tab.effects": {"en": "Effects", "zh-Hans": "特效", "zh-Hant": "特效", "ja": "エフェクト"},
    "tab.lyrics": {"en": "Lyrics", "zh-Hans": "歌词", "zh-Hant": "歌詞", "ja": "歌詞"},
    "tab.position": {"en": "Position", "zh-Hans": "位置", "zh-Hant": "位置", "ja": "位置"},
    "tab.sources": {"en": "Sources", "zh-Hans": "来源", "zh-Hant": "來源", "ja": "ソース"},
    "tab.general": {"en": "General", "zh-Hans": "通用", "zh-Hant": "通用", "ja": "一般"},

    "set.app_icon": {"en": "Tray icon", "zh-Hans": "托盘图标", "zh-Hant": "系統匣圖示", "ja": "トレイアイコン"},
    "set.app_icon_hint": {"en": "Used for the system tray and the window icon.",
                          "zh-Hans": "用于系统托盘和窗口图标。",
                          "zh-Hant": "用於系統匣與視窗圖示。",
                          "ja": "システムトレイとウィンドウアイコンに使われます。"},
    "set.font_family": {"en": "Font", "zh-Hans": "字体", "zh-Hant": "字型", "ja": "フォント"},
    "set.font_weight": {"en": "Weight", "zh-Hans": "字重", "zh-Hant": "字重", "ja": "太さ"},
    "weight.thin": {"en": "Thin", "zh-Hans": "特细", "zh-Hant": "特細", "ja": "シン"},
    "weight.extralight": {"en": "Extra light", "zh-Hans": "极细", "zh-Hant": "極細", "ja": "エクストラライト"},
    "weight.light": {"en": "Light", "zh-Hans": "细", "zh-Hant": "細", "ja": "ライト"},
    "weight.regular": {"en": "Regular", "zh-Hans": "常规", "zh-Hant": "標準", "ja": "レギュラー"},
    "weight.medium": {"en": "Medium", "zh-Hans": "中等", "zh-Hant": "中等", "ja": "ミディアム"},
    "weight.semibold": {"en": "Semi bold", "zh-Hans": "次粗", "zh-Hant": "次粗", "ja": "セミボールド"},
    "weight.bold": {"en": "Bold", "zh-Hans": "粗体", "zh-Hant": "粗體", "ja": "ボールド"},
    "weight.extrabold": {"en": "Extra bold", "zh-Hans": "特粗", "zh-Hant": "特粗", "ja": "エクストラボールド"},
    "weight.black": {"en": "Black", "zh-Hans": "极粗", "zh-Hant": "極粗", "ja": "ブラック"},
    "set.font_size": {"en": "Main line size", "zh-Hans": "主歌词字号",
                      "zh-Hant": "主歌詞字級", "ja": "メイン行のサイズ"},
    "set.context_font_size": {"en": "Context line size", "zh-Hans": "上下句字号",
                              "zh-Hant": "上下句字級", "ja": "前後の行のサイズ"},
    "set.translation_font_size": {"en": "Translation size", "zh-Hans": "翻译字号",
                                  "zh-Hant": "翻譯字級", "ja": "翻訳のサイズ"},
    "set.opacity": {"en": "Panel opacity", "zh-Hans": "面板不透明度",
                    "zh-Hant": "面板不透明度", "ja": "パネル不透明度"},
    "set.panel_style": {"en": "Panel style", "zh-Hans": "面板样式", "zh-Hant": "面板樣式", "ja": "パネルの種類"},
    "set.panel_size": {"en": "Panel size", "zh-Hans": "面板大小", "zh-Hant": "面板大小", "ja": "パネルサイズ"},
    "panelsize.fit": {"en": "Fit to text", "zh-Hans": "随文字宽度",
                      "zh-Hant": "隨文字寬度", "ja": "文字幅に合わせる"},
    "panelsize.fixed": {"en": "Fixed width", "zh-Hans": "固定宽度", "zh-Hant": "固定寬度", "ja": "固定幅"},
    "set.panel_width": {"en": "Panel width", "zh-Hans": "面板宽度", "zh-Hant": "面板寬度", "ja": "パネル幅"},
    "set.panel_size_hint": {
        "en": "Fixed width keeps the panel the same size no matter how long the line is; long lines scroll.",
        "zh-Hans": "固定宽度让面板大小不随歌词长短变化；过长的歌词会滚动显示。",
        "zh-Hant": "固定寬度讓面板大小不隨歌詞長短變化；過長的歌詞會捲動顯示。",
        "ja": "固定幅にすると歌詞の長さに関わらずパネルの大きさが一定になります（長い行はスクロール）。",
    },
    "set.panel.pill": {"en": "Black panel", "zh-Hans": "黑色面板", "zh-Hant": "黑色面板", "ja": "黒パネル"},
    "set.panel.white": {"en": "White panel", "zh-Hans": "白色面板", "zh-Hant": "白色面板", "ja": "白パネル"},
    "set.panel.frost": {"en": "Frosted glass", "zh-Hans": "毛玻璃面板",
                        "zh-Hant": "毛玻璃面板", "ja": "すりガラス"},
    "set.panel.text": {"en": "No panel", "zh-Hans": "无面板", "zh-Hant": "無面板", "ja": "パネルなし"},
    "set.panel_tint": {"en": "Panel follows accent color", "zh-Hans": "面板颜色跟随强调色",
                       "zh-Hant": "面板顏色跟隨強調色", "ja": "パネル色をアクセントに合わせる"},
    "set.panel_hint": {
        "en": "Frosted glass needs KWin/KDE; elsewhere it falls back to a translucent panel. "
              "Each panel style keeps its own opacity (black can go fully transparent, frosted to pure blur).",
        "zh-Hans": "毛玻璃需要 KWin/KDE 桌面；其他环境回退为半透明面板。每种面板样式各自记住不透明度"
                   "（黑色可全透明，毛玻璃可纯模糊）。",
        "zh-Hant": "毛玻璃需要 KWin/KDE 桌面；其他環境回退為半透明面板。每種面板樣式各自記住不透明度"
                   "（黑色可全透明，毛玻璃可純模糊）。",
        "ja": "すりガラスは KWin/KDE が必要（他環境では半透明パネルに）。不透明度はスタイルごとに保持"
              "（黒は完全透明、すりガラスは純ぼかしまで）。",
    },
    "set.fx_animate": {"en": "Animations", "zh-Hans": "动画", "zh-Hant": "動畫", "ja": "アニメーション"},
    "set.fx_glow": {"en": "Glow on the active line", "zh-Hans": "当前行发光",
                    "zh-Hant": "當前行發光", "ja": "現在行のグロー"},
    "set.fx_word_pop": {"en": "Highlight the current word", "zh-Hans": "突出正在唱的字词",
                        "zh-Hant": "突出正在唱的字詞", "ja": "歌っている語を強調"},
    "set.fx_intensity": {"en": "Effect intensity", "zh-Hans": "特效强度",
                         "zh-Hant": "特效強度", "ja": "エフェクトの強さ"},
    "fxintensity.subtle": {"en": "Subtle", "zh-Hans": "轻微", "zh-Hant": "輕微", "ja": "控えめ"},
    "fxintensity.expressive": {"en": "Expressive", "zh-Hans": "明显", "zh-Hant": "明顯", "ja": "はっきり"},
    "set.accent": {"en": "Accent color", "zh-Hans": "强调色", "zh-Hant": "強調色", "ja": "アクセント色"},
    "set.accent.custom": {"en": "Custom", "zh-Hans": "自定义", "zh-Hant": "自訂", "ja": "カスタム"},
    "accent.pink": {"en": "Pink", "zh-Hans": "粉", "zh-Hant": "粉紅", "ja": "ピンク"},
    "accent.red": {"en": "Red", "zh-Hans": "红", "zh-Hant": "紅", "ja": "レッド"},
    "accent.orange": {"en": "Orange", "zh-Hans": "橙", "zh-Hant": "橙", "ja": "オレンジ"},
    "accent.yellow": {"en": "Yellow", "zh-Hans": "黄", "zh-Hant": "黃", "ja": "イエロー"},
    "accent.green": {"en": "Green", "zh-Hans": "绿", "zh-Hant": "綠", "ja": "グリーン"},
    "accent.teal": {"en": "Teal", "zh-Hans": "青绿", "zh-Hant": "青綠", "ja": "ティール"},
    "accent.cyan": {"en": "Cyan", "zh-Hans": "青蓝", "zh-Hant": "青藍", "ja": "シアン"},
    "accent.blue": {"en": "Blue", "zh-Hans": "蓝", "zh-Hant": "藍", "ja": "ブルー"},
    "accent.purple": {"en": "Purple", "zh-Hans": "紫", "zh-Hant": "紫", "ja": "パープル"},
    "accent.white": {"en": "White", "zh-Hans": "白", "zh-Hant": "白", "ja": "ホワイト"},
    "set.accent.pick": {"en": "Custom…", "zh-Hans": "自定义…", "zh-Hant": "自訂…", "ja": "カスタム…"},
    "set.karaoke": {"en": "Word-by-word highlight", "zh-Hans": "逐字高亮",
                    "zh-Hant": "逐字高亮", "ja": "文字単位ハイライト"},
    "set.lead": {"en": "Sync offset", "zh-Hans": "同步偏移", "zh-Hant": "同步偏移", "ja": "同期オフセット"},
    "set.lead.tip": {"en": "Positive advances the highlight (compensates latency), negative delays it.",
                     "zh-Hans": "正值让高亮提前（补偿延迟），负值让高亮滞后。",
                     "zh-Hant": "正值讓高亮提前（補償延遲），負值讓高亮延後。",
                     "ja": "正の値でハイライトを早め（遅延を補正）、負の値で遅らせます。"},
    "set.show_translation": {"en": "Show translation", "zh-Hans": "显示翻译",
                             "zh-Hant": "顯示翻譯", "ja": "翻訳を表示"},
    "set.position": {"en": "Screen edge", "zh-Hans": "屏幕边缘", "zh-Hant": "螢幕邊緣", "ja": "画面の端"},
    "set.top": {"en": "Top", "zh-Hans": "顶部", "zh-Hant": "頂部", "ja": "上"},
    "set.bottom": {"en": "Bottom", "zh-Hans": "底部", "zh-Hant": "底部", "ja": "下"},
    "set.margin_edge": {"en": "Distance from edge", "zh-Hans": "距边缘距离",
                        "zh-Hant": "距邊緣距離", "ja": "端からの距離"},
    "set.margin_x": {"en": "Horizontal offset", "zh-Hans": "水平偏移",
                     "zh-Hant": "水平偏移", "ja": "水平オフセット"},
    "set.passthrough": {"en": "Click-through by default (locked)", "zh-Hans": "默认鼠标穿透（锁定）",
                        "zh-Hant": "預設滑鼠穿透（鎖定）", "ja": "既定でクリック透過（ロック）"},
    "set.box_hint": {
        "en": "The overlay sits inside a transparent band; unlock it to drag the whole thing. "
              "Its size, background, and fonts are set in the Appearance tab.",
        "zh-Hans": "浮窗位于一块透明区域内，解锁后可拖动整体位置。大小、背景和字体在「外观」标签页设置。",
        "zh-Hant": "浮窗位於一塊透明區域內，解鎖後可拖動整體位置。大小、背景與字型在「外觀」分頁設定。",
        "ja": "オーバーレイは透明な帯の中にあり、ロックを解除するとドラッグで全体を移動できます。"
              "サイズ・背景・フォントは「外観」タブで設定します。",
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
    "set.prefer_best": {
        "en": "Prefer best-matching lyrics",
        "zh-Hans": "优先匹配最佳歌词",
        "zh-Hant": "優先匹配最佳歌詞",
        "ja": "最も一致する歌詞を優先",
    },
    "set.prefer_best_hint": {
        "en": "Query the enabled sources at the same time and keep the highest-confidence "
              "match (ties keep your order). Off = stop at the first source that has lyrics.",
        "zh-Hans": "同时查询已启用的来源，保留匹配度最高的一个（相同则按你的排序）。"
                   "关闭则按顺序取第一个有歌词的来源。",
        "zh-Hant": "同時查詢已啟用的來源，保留匹配度最高的一個（相同則按你的排序）。"
                   "關閉則按順序取第一個有歌詞的來源。",
        "ja": "有効なソースを同時に照会し、最も確度の高い一致を採用（同点は指定順）。"
              "オフにすると最初に歌詞が見つかったソースで停止。",
    },
    "set.cache_enabled": {
        "en": "Enable local lyrics cache",
        "zh-Hans": "启用本地歌词缓存",
        "zh-Hant": "啟用本地歌詞快取",
        "ja": "ローカル歌詞キャッシュを有効化",
    },
    "btn.clear_cache": {
        "en": "Clear lyrics cache",
        "zh-Hans": "清除歌词缓存",
        "zh-Hant": "清除歌詞快取",
        "ja": "歌詞キャッシュを消去",
    },
    "set.lyrics_script": {"en": "Convert lyrics", "zh-Hans": "歌词转换",
                          "zh-Hant": "歌詞轉換", "ja": "歌詞変換"},
    "lyricscript.off": {"en": "Don't convert", "zh-Hans": "不转换", "zh-Hant": "不轉換", "ja": "変換しない"},
    "lyricscript.hans": {"en": "To Simplified", "zh-Hans": "转为简体",
                         "zh-Hant": "轉為簡體", "ja": "簡体字に"},
    "lyricscript.hant": {"en": "To Traditional", "zh-Hans": "转为繁体",
                         "zh-Hant": "轉為繁體", "ja": "繁体字に"},
    "set.lyrics_script_hint": {"en": "Convert the displayed lyrics between Simplified and Traditional "
                                     "(display only; best-effort).",
                               "zh-Hans": "把显示的歌词在简体与繁体之间转换（仅影响显示，尽力而为）。",
                               "zh-Hant": "把顯示的歌詞在簡體與繁體之間轉換（僅影響顯示，盡力而為）。",
                               "ja": "表示する歌詞を簡体字／繁体字に変換します（表示のみ、ベストエフォート）。"},
    "set.language": {"en": "Language", "zh-Hans": "语言", "zh-Hant": "語言", "ja": "言語"},
    "set.language_hint": {"en": "Takes effect after restart.", "zh-Hans": "重启后生效。",
                          "zh-Hant": "重啟後生效。", "ja": "再起動後に反映されます。"},
    "set.theme": {"en": "Theme", "zh-Hans": "主题", "zh-Hant": "主題", "ja": "テーマ"},
    "theme.auto": {"en": "Follow system", "zh-Hans": "跟随系统",
                   "zh-Hant": "跟隨系統", "ja": "システムに従う"},
    "theme.light": {"en": "Light", "zh-Hans": "浅色", "zh-Hant": "淺色", "ja": "ライト"},
    "theme.dark": {"en": "Dark", "zh-Hans": "深色", "zh-Hant": "深色", "ja": "ダーク"},
    "set.frost_window": {"en": "Frosted-glass window", "zh-Hans": "毛玻璃窗口",
                         "zh-Hant": "毛玻璃視窗", "ja": "すりガラスウィンドウ"},
    "set.frost_window_hint": {"en": "Frosted glass needs KDE Wayland; a solid window elsewhere.",
                              "zh-Hans": "毛玻璃需要 KDE Wayland；其他环境为不透明窗口。",
                              "zh-Hant": "毛玻璃需要 KDE Wayland；其他環境為不透明視窗。",
                              "ja": "すりガラスは KDE Wayland が必要（他環境では不透明ウィンドウ）。"},
    "btn.restart": {"en": "Restart now", "zh-Hans": "立即重启",
                    "zh-Hant": "立即重啟", "ja": "今すぐ再起動"},
    "btn.ok": {"en": "OK", "zh-Hans": "确定", "zh-Hant": "確定", "ja": "OK"},
    "btn.cancel": {"en": "Cancel", "zh-Hans": "取消", "zh-Hant": "取消", "ja": "キャンセル"},
    "btn.apply": {"en": "Apply", "zh-Hans": "应用", "zh-Hant": "套用", "ja": "適用"},
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
