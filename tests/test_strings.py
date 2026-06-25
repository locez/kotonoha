from kotonoha import strings


def test_each_language():
    strings.set_language("en")
    assert strings.t("tray.quit") == "Quit"
    strings.set_language("zh-Hans")
    assert strings.t("tray.quit") == "退出"
    strings.set_language("zh-Hant")
    assert strings.t("tray.quit") == "結束"
    strings.set_language("ja")
    assert strings.t("tray.quit") == "終了"


def test_unknown_key_returns_key():
    strings.set_language("en")
    assert strings.t("nope.nope") == "nope.nope"


def test_resolve_ui_language():
    assert strings.resolve_ui_language("zh_TW") == "zh-Hant"
    assert strings.resolve_ui_language("ja_JP") == "ja"
    assert strings.resolve_ui_language("ko") == "en"  # unsupported -> fallback
    assert strings.resolve_ui_language("fr_FR") == "en"
    assert strings.resolve_ui_language("zh_CN") == "zh-Hans"


def test_auto_is_supported():
    strings.set_language("auto")
    assert strings.current_language() in ("en", "zh-Hans", "zh-Hant", "ja")


def test_all_keys_have_all_languages():
    langs = ("en", "zh-Hans", "zh-Hant", "ja")
    for key, entry in strings.STRINGS.items():
        for lang in langs:
            assert entry.get(lang), f"missing {lang} for {key}"
