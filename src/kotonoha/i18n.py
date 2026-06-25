"""Translation-language resolution.

Apple Music TTML embeds translations tagged with BCP-47-ish language codes
(e.g. ``zh-Hans``, ``zh-Hant``, ``en``, ``ja``). The user picks which one to
show; by default we derive it from the system locale. The probe then extracts
that language from the TTML.

The mapping is a pure function so it can be unit-tested; the QLocale lookup is a
thin wrapper around it.
"""

from __future__ import annotations

AUTO = "auto"

# Languages we offer in the UI and can ask the probe to extract.
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
)

_SUPPORTED_TAGS = {tag for tag, _ in SUPPORTED_LANGUAGES}
_DEFAULT_TAG = "en"


def normalize_to_apple_tag(locale_name: str) -> str:
    """Map a locale string (``zh_CN``, ``zh-Hant-TW``, ``en_US`` ...) to an Apple tag.

    Falls back to ``en`` for anything unrecognised.
    """
    if not locale_name:
        return _DEFAULT_TAG
    name = locale_name.replace("_", "-").lower()
    parts = name.split("-")
    primary = parts[0]
    rest = parts[1:]

    if primary == "zh":
        # Script or region decides Simplified vs Traditional.
        if any(p in ("hant", "tw", "hk", "mo") for p in rest):
            return "zh-Hant"
        return "zh-Hans"

    if primary in _SUPPORTED_TAGS:
        return primary

    return _DEFAULT_TAG


def system_translation_language(locale_name: str | None = None) -> str:
    """Resolve the system's preferred translation language as an Apple tag.

    ``locale_name`` is injectable for testing; when omitted it is read from
    :class:`PyQt6.QtCore.QLocale`.
    """
    if locale_name is None:
        from PyQt6.QtCore import QLocale

        locale_name = QLocale.system().name()
    return normalize_to_apple_tag(locale_name)


def resolve_translation_language(value: str, locale_name: str | None = None) -> str:
    """Turn a config value (``auto`` or an explicit tag) into a concrete Apple tag."""
    if not value or value == AUTO:
        return system_translation_language(locale_name)
    return normalize_to_apple_tag(value)
