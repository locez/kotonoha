"""Localized labels for lyrics API translation settings, services, and cache manager."""

from typing import Final

TRANSLATION_STRINGS: Final[dict[str, dict[str, str]]] = {
    "set.translation_language": {
        "en": "Translation language",
        "zh-Hans": "翻译目标语言",
        "zh-Hant": "翻譯目標語言",
        "ja": "翻訳先の言語",
    },
    "set.translation_language_auto": {
        "en": "Follow system language",
        "zh-Hans": "跟随系统语言",
        "zh-Hant": "跟隨系統語言",
        "ja": "システムの言語に従う",
    },
    "set.translation_policy": {
        "en": "Online translation",
        "zh-Hans": "在线翻译策略",
        "zh-Hant": "線上翻譯策略",
        "ja": "オンライン翻訳",
    },
    "transpolicy.off": {
        "en": "Off (source translations only)",
        "zh-Hans": "关闭（仅使用歌词源自带翻译）",
        "zh-Hant": "關閉（僅使用歌詞來源內建翻譯）",
        "ja": "オフ（ソース付属の翻訳のみ）",
    },
    "transpolicy.missing": {
        "en": "Translate when missing",
        "zh-Hans": "无自带翻译时自动翻译",
        "zh-Hant": "無內建翻譯時自動翻譯",
        "ja": "翻訳がない場合のみ翻訳",
    },
    "transpolicy.replace": {
        "en": "Always translate to target language",
        "zh-Hans": "始终翻译为目标语言",
        "zh-Hant": "始終翻譯為目標語言",
        "ja": "常に翻訳先の言語へ翻訳",
    },
    "set.translation_services": {
        "en": "Translation services",
        "zh-Hans": "翻译服务（按优先级）",
        "zh-Hant": "翻譯服務（依優先順序）",
        "ja": "翻訳サービス（優先順）",
    },
    "set.translation_services_hint": {
        "en": (
            "Checked services run from top to bottom. Drag items to reorder priority; "
            "if one fails, the next enabled service takes over automatically."
        ),
        "zh-Hans": "勾选的服务会按从上到下的顺序尝试，拖拽条目可调整优先级；前面失败时自动回退到下一个服务。",
        "zh-Hant": "勾選的服務會由上而下依序嘗試，拖曳項目可調整優先順序；前者失敗時自動退回下一個服務。",
        "ja": (
            "チェックされたサービスを上から順に試行します。"
            "ドラッグで優先順を変更でき、失敗時は次のサービスへ自動で切り替わります。"
        ),
    },
    "btn.add_translation_service": {
        "en": "Add",
        "zh-Hans": "添加",
        "zh-Hant": "新增",
        "ja": "追加",
    },
    "btn.edit_translation_service": {
        "en": "Edit",
        "zh-Hans": "编辑",
        "zh-Hant": "編輯",
        "ja": "編集",
    },
    "btn.remove_translation_service": {
        "en": "Remove",
        "zh-Hans": "删除",
        "zh-Hant": "刪除",
        "ja": "削除",
    },
    "tservice.add_title": {
        "en": "Add translation service",
        "zh-Hans": "添加翻译服务",
        "zh-Hant": "新增翻譯服務",
        "ja": "翻訳サービスを追加",
    },
    "tservice.edit_title": {
        "en": "Edit translation service",
        "zh-Hans": "编辑翻译服务",
        "zh-Hant": "編輯翻譯服務",
        "ja": "翻訳サービスを編集",
    },
    "tservice.name": {
        "en": "Display name",
        "zh-Hans": "显示名称",
        "zh-Hant": "顯示名稱",
        "ja": "表示名",
    },
    "tservice.name_placeholder": {
        "en": "e.g. Gemini Primary, My Custom API",
        "zh-Hans": "例如：Gemini 主力、自定义接口 2",
        "zh-Hant": "例如：Gemini 主力、自訂介面 2",
        "ja": "例：Gemini メイン、カスタム API",
    },
    "tservice.badge.key_saved": {
        "en": "Key saved",
        "zh-Hans": "已配密钥",
        "zh-Hant": "已設定金鑰",
        "ja": "キー保存済み",
    },
    "tservice.badge.key_pending": {
        "en": "Key pending apply",
        "zh-Hans": "待应用保存",
        "zh-Hant": "待套用儲存",
        "ja": "適用待ち",
    },
    "tservice.badge.key_missing": {
        "en": "No key",
        "zh-Hans": "未配密钥",
        "zh-Hant": "未設定金鑰",
        "ja": "キー未設定",
    },
    "tservice.badge.key_not_needed": {
        "en": "Local · no key",
        "zh-Hans": "本地 · 免密钥",
        "zh-Hant": "本機 · 免金鑰",
        "ja": "ローカル・キー不要",
    },
    "tservice.error.missing_model": {
        "en": "Please enter a model name.",
        "zh-Hans": "请填写模型名称。",
        "zh-Hant": "請填寫模型名稱。",
        "ja": "モデル名を入力してください。",
    },
    "transprovider.deepl": {
        "en": "DeepL API (Free 500k/mo & Pro)",
        "zh-Hans": "DeepL 官方 API（免费 50 万字符/月 & Pro）",
        "zh-Hant": "DeepL 官方 API（免費 50 萬字元/月 & Pro）",
        "ja": "DeepL 公式 API（無料 月50万文字 & Pro）",
    },
    "set.translation_preset": {
        "en": "Service preset",
        "zh-Hans": "服务预设",
        "zh-Hant": "服務預設",
        "ja": "サービスプリセット",
    },
    "transpreset.gemini": {
        "en": "Google Gemini (AI Studio)",
        "zh-Hans": "Google Gemini (AI Studio)",
        "zh-Hant": "Google Gemini (AI Studio)",
        "ja": "Google Gemini (AI Studio)",
    },
    "transpreset.deepseek": {
        "en": "DeepSeek",
        "zh-Hans": "DeepSeek",
        "zh-Hant": "DeepSeek",
        "ja": "DeepSeek",
    },
    "transpreset.openrouter": {
        "en": "OpenRouter",
        "zh-Hans": "OpenRouter",
        "zh-Hant": "OpenRouter",
        "ja": "OpenRouter",
    },
    "transpreset.ollama": {
        "en": "Ollama (Local)",
        "zh-Hans": "Ollama（本地）",
        "zh-Hant": "Ollama（本機）",
        "ja": "Ollama（ローカル）",
    },
    "transpreset.custom": {
        "en": "Custom OpenAI-compatible endpoint",
        "zh-Hans": "自定义 OpenAI 兼容接口",
        "zh-Hant": "自訂 OpenAI 相容介面",
        "ja": "カスタム OpenAI 互換エンドポイント",
    },
    "set.translation_base_url": {
        "en": "API base URL",
        "zh-Hans": "API 地址",
        "zh-Hant": "API 位址",
        "ja": "API ベース URL",
    },
    "set.translation_model": {
        "en": "Model",
        "zh-Hans": "模型名称",
        "zh-Hant": "模型名稱",
        "ja": "モデル名",
    },
    "set.translation_prompt": {
        "en": "Translation prompt",
        "zh-Hans": "翻译提示词",
        "zh-Hant": "翻譯提示詞",
        "ja": "翻訳プロンプト",
    },
    "set.translation_prompt_hint": {
        "en": (
            "Shared style prompt for OpenAI-compatible services (e.g. poetic, concise, regional idioms). "
            "JSON line alignment is enforced automatically."
        ),
        "zh-Hans": "供所有 OpenAI 兼容服务共用的翻译风格提示词（如诗意、直白、口语化等）；逐行 JSON 对齐会自动附加。",
        "zh-Hant": "供所有 OpenAI 相容服務共用的翻譯風格提示詞（如詩意、直白、口語化等）；逐行 JSON 對齊會自動附加。",
        "ja": "OpenAI 互換サービス共通の翻訳スタイル指示です（行単位の JSON 整列形式は自動で付与されます）。",
    },
    "set.translation_api_key": {
        "en": "API key",
        "zh-Hans": "API 密钥",
        "zh-Hant": "API 金鑰",
        "ja": "API キー",
    },
    "set.translation_api_key.placeholder": {
        "en": "Enter API key (stored in system keyring)",
        "zh-Hans": "输入 API 密钥（将保存到系统密钥环）",
        "zh-Hant": "輸入 API 金鑰（將儲存至系統金鑰圈）",
        "ja": "API キーを入力（システムキーリングに保存）",
    },
    "set.translation_api_key.saved_placeholder": {
        "en": "Saved in system keyring — enter a new key to replace",
        "zh-Hans": "已保存至系统密钥环 — 输入新密钥可替换",
        "zh-Hant": "已儲存至系統金鑰圈 — 輸入新金鑰可替換",
        "ja": "キーリングに保存済み — 新しいキーを入力して上書き",
    },
    "set.translation_key.saved": {
        "en": "This service's API key is saved in your system keyring.",
        "zh-Hans": "该服务的 API 密钥已安全保存在系统密钥环中。",
        "zh-Hant": "該服務的 API 金鑰已安全儲存在系統金鑰圈中。",
        "ja": "このサービスの API キーはシステムキーリングに保存されています。",
    },
    "set.translation_key.not_saved.deepl": {
        "en": (
            "No DeepL API key saved yet. "
            "Free keys ending in :fx route to api-free.deepl.com automatically."
        ),
        "zh-Hans": "尚未保存 DeepL API 密钥。以 :fx 结尾的免费密钥会自动走免费端点，无需额外配置。",
        "zh-Hant": "尚未儲存 DeepL API 金鑰。以 :fx 結尾的免費金鑰會自動走免費端點，無需額外設定。",
        "ja": (
            "DeepL API キーは未保存です。"
            ":fx で終わる無料キーは自動的に無料エンドポイントへ接続します。"
        ),
    },
    "set.translation_key.not_saved.openai": {
        "en": "No API key saved yet. Enter a key and click Apply in Settings to store it in your system keyring.",
        "zh-Hans": "尚未保存 API 密钥。输入密钥并在主设置页点击「应用」即可保存到系统密钥环。",
        "zh-Hant": "尚未儲存 API 金鑰。輸入金鑰並在主設定頁點擊「套用」即可儲存至系統金鑰圈。",
        "ja": "API キーは未保存です。キーを入力して設定で「適用」を押すとキーリングに保存されます。",
    },
    "set.translation_key.ollama": {
        "en": "Local Ollama endpoints do not require an API key.",
        "zh-Hans": "本地 Ollama 无需填写 API 密钥。",
        "zh-Hant": "本機 Ollama 無需填寫 API 金鑰。",
        "ja": "ローカルの Ollama は API キー不要です。",
    },
    "set.translation_key.unavailable": {
        "en": (
            "System keyring is unavailable ({reason}). "
            "Set KOTONOHA_TRANSLATION_API_KEY (or service-specific env var) instead."
        ),
        "zh-Hans": (
            "系统密钥环不可用（{reason}）。"
            "请改用环境变量 KOTONOHA_TRANSLATION_API_KEY（或对应服务变量）提供密钥。"
        ),
        "zh-Hant": (
            "系統金鑰圈無法使用（{reason}）。"
            "請改用環境變數 KOTONOHA_TRANSLATION_API_KEY（或對應服務變數）提供金鑰。"
        ),
        "ja": (
            "システムキーリングを利用できません（{reason}）。"
            "代わりに環境変数 KOTONOHA_TRANSLATION_API_KEY を設定してください。"
        ),
    },
    "btn.clear_translation_key": {
        "en": "Remove saved key",
        "zh-Hans": "删除已保存密钥",
        "zh-Hant": "刪除已儲存金鑰",
        "ja": "保存済みキーを削除",
    },
    "btn.manage_translation_cache": {
        "en": "Manage translation cache",
        "zh-Hans": "管理翻译缓存",
        "zh-Hant": "管理翻譯快取",
        "ja": "翻訳キャッシュを管理",
    },
    "btn.clear_translation_cache": {
        "en": "Clear translation cache",
        "zh-Hans": "清除翻译缓存",
        "zh-Hant": "清除翻譯快取",
        "ja": "翻訳キャッシュを消去",
    },
    "tcache.title": {
        "en": "Translation cache",
        "zh-Hans": "翻译缓存",
        "zh-Hant": "翻譯快取",
        "ja": "翻訳キャッシュ",
    },
    "tcache.subtitle": {
        "en": "Manage cached API translations keyed by lyric content and target language.",
        "zh-Hans": "管理按歌词内容和目标语言缓存的在线翻译结果，删除后下次播放会重新翻译。",
        "zh-Hant": "管理依歌詞內容與目標語言快取的線上翻譯結果，刪除後下次播放會重新翻譯。",
        "ja": "歌詞内容と翻訳先言語ごとに保存された API 翻訳キャッシュを管理します。",
    },
    "tcache.search_placeholder": {
        "en": "Search title, artist, language, service or model",
        "zh-Hans": "搜索标题、艺术家、目标语言、服务或模型",
        "zh-Hant": "搜尋標題、藝人、目標語言、服務或模型",
        "ja": "タイトル、アーティスト、言語、サービス、モデルを検索",
    },
    "tcache.clear_confirm": {
        "en": "Delete every cached lyric translation? Source lyrics cache will not be affected.",
        "zh-Hans": "确定删除全部翻译缓存吗？原始歌词缓存不会受影响。",
        "zh-Hant": "確定刪除全部翻譯快取嗎？原始歌詞快取不會受影響。",
        "ja": "すべての翻訳キャッシュを削除しますか？元の歌詞キャッシュには影響しません。",
    },
    "tcache.clear_done": {
        "en": "Translation cache cleared",
        "zh-Hans": "翻译缓存已清除",
        "zh-Hant": "翻譯快取已清除",
        "ja": "翻訳キャッシュを消去しました",
    },
    "tcache.column.language": {
        "en": "Language",
        "zh-Hans": "目标语言",
        "zh-Hant": "目標語言",
        "ja": "言語",
    },
    "tcache.column.model": {
        "en": "Model",
        "zh-Hans": "模型",
        "zh-Hant": "模型",
        "ja": "モデル",
    },
    "tcache.column.lines": {
        "en": "Lines",
        "zh-Hans": "行数",
        "zh-Hant": "行數",
        "ja": "行数",
    },
    "btn.edit_translation": {
        "en": "Edit",
        "zh-Hans": "编辑",
        "zh-Hant": "編輯",
        "ja": "編集",
    },
    "btn.save": {
        "en": "Save",
        "zh-Hans": "保存",
        "zh-Hant": "儲存",
        "ja": "保存",
    },
    "tcache.edit_title": {
        "en": "Edit cached translation",
        "zh-Hans": "编辑翻译缓存",
        "zh-Hant": "編輯翻譯快取",
        "ja": "翻訳キャッシュを編集",
    },
    "tcache.edit_hint": {
        "en": (
            "Double-click any cell in the Translation column to edit. "
            "Line count stays locked to keep timestamps aligned."
        ),
        "zh-Hans": "双击「翻译」列任意单元格即可修改，行数与原歌词一一对应以保持时间轴对齐。",
        "zh-Hant": "雙擊「翻譯」欄任意儲存格即可修改，行數與原歌詞一一對應以保持時間軸對齊。",
        "ja": "「翻訳」列のセルをダブルクリックして編集できます（タイムスタンプ同期のため行数は固定です）。",
    },
    "tcache.edit_no_source_notice": {
        "en": (
            "Original lyrics were not saved for this older cache entry. "
            "Replay the track (or delete and re-translate) to record original lines for side-by-side editing."
        ),
        "zh-Hans": (
            "该条目未保存原文歌词（由较早缓存生成），因此仅展示译文；"
            "重新播放该歌曲或删除后重新翻译即可显示原文对照。"
        ),
        "zh-Hant": (
            "該項目未儲存原文歌詞（由較早快取產生），因此僅顯示譯文；"
            "重新播放該歌曲或刪除後重新翻譯即可顯示原文對照。"
        ),
        "ja": (
            "このキャッシュ項目には元の歌詞が保存されていません。"
            "曲を再生し直すか削除して再翻訳すると、原文と並べて編集できるようになります。"
        ),
    },
    "tcache.column.line_no": {
        "en": "#",
        "zh-Hans": "#",
        "zh-Hant": "#",
        "ja": "#",
    },
    "tcache.column.time": {
        "en": "Time",
        "zh-Hans": "时间",
        "zh-Hant": "時間",
        "ja": "時間",
    },
    "tcache.column.source": {
        "en": "Original",
        "zh-Hans": "原文",
        "zh-Hant": "原文",
        "ja": "原文",
    },
    "tcache.column.translation": {
        "en": "Translation",
        "zh-Hans": "翻译",
        "zh-Hant": "翻譯",
        "ja": "翻訳",
    },
    "tcache.saved": {
        "en": "Translation updated",
        "zh-Hans": "翻译已保存",
        "zh-Hant": "翻譯已儲存",
        "ja": "翻訳を保存しました",
    },
    "tcache.save_missing": {
        "en": "This cache entry no longer exists",
        "zh-Hans": "该翻译缓存条目已不存在",
        "zh-Hant": "該翻譯快取項目已不存在",
        "ja": "このキャッシュ項目はすでにありません",
    },
    "overlay.translation.translating": {
        "en": "Translating…",
        "zh-Hans": "正在翻译…",
        "zh-Hant": "正在翻譯…",
        "ja": "翻訳中…",
    },
    "overlay.translation.failed": {
        "en": "Translation failed",
        "zh-Hans": "翻译失败",
        "zh-Hant": "翻譯失敗",
        "ja": "翻訳に失敗しました",
    },
    "overlay.translation.unavailable": {
        "en": "No translation available",
        "zh-Hans": "暂无翻译",
        "zh-Hant": "暫無翻譯",
        "ja": "翻訳はありません",
    },
}

__all__ = ["TRANSLATION_STRINGS"]
