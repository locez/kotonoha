from kotonoha.i18n import (
    normalize_to_apple_tag,
    resolve_translation_language,
    system_translation_language,
)


def test_simplified_chinese_variants():
    for name in ("zh", "zh_CN", "zh-Hans", "zh-Hans-CN", "ZH_cn"):
        assert normalize_to_apple_tag(name) == "zh-Hans"


def test_traditional_chinese_variants():
    for name in ("zh_TW", "zh-Hant", "zh-Hant-TW", "zh_HK", "zh_MO"):
        assert normalize_to_apple_tag(name) == "zh-Hant"


def test_english_and_others():
    assert normalize_to_apple_tag("en_US") == "en"
    assert normalize_to_apple_tag("ja_JP") == "ja"
    assert normalize_to_apple_tag("ko_KR") == "ko"
    assert normalize_to_apple_tag("fr_FR") == "fr"


def test_unknown_falls_back_to_english():
    assert normalize_to_apple_tag("xx_YY") == "en"
    assert normalize_to_apple_tag("") == "en"


def test_resolve_auto_uses_system_locale():
    assert resolve_translation_language("auto", locale_name="zh_CN") == "zh-Hans"


def test_resolve_explicit_tag():
    assert resolve_translation_language("ja", locale_name="zh_CN") == "ja"


def test_system_translation_language_injectable():
    assert system_translation_language("zh_TW") == "zh-Hant"
