"""Translation-language resolution.

Apple Music TTML embeds translations tagged with BCP-47-ish language codes
(e.g. ``zh-Hans``, ``zh-Hant``, ``en``, ``ja``). API translation supports a
wider BCP-47 set including regional variants such as ``pt-PT`` and ``pt-BR``.

All normalization functions are pure so they can be unit-tested without Qt;
only the ``QLocale`` lookup touches Qt when no explicit locale is injected.
"""

from __future__ import annotations

import re

AUTO = "auto"

# Languages offered to Apple Music / Cider TTML translation lookup.
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

# Languages offered in Settings for lyrics translation, preserving regional
# variants that matter for API translators (e.g. pt-PT vs pt-BR).
TRANSLATION_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("auto", "Auto (System)"),
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("pt-PT", "Português (Portugal)"),
    ("pt-BR", "Português (Brasil)"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("it", "Italiano"),
    ("ru", "Русский"),
    ("ar", "العربية"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("tr", "Türkçe"),
    ("uk", "Українська"),
    ("th", "ไทย"),
    ("vi", "Tiếng Việt"),
    ("id", "Bahasa Indonesia"),
)

_LANGUAGE_DISPLAY_NAMES: dict[str, str] = {
    **{tag: label for tag, label in TRANSLATION_LANGUAGES if tag != AUTO},
    "en-GB": "English (UK)",
    "en-US": "English (US)",
}

_LANGUAGE_ENGLISH_NAMES: dict[str, str] = {
    "zh-Hans": "Simplified Chinese (zh-Hans)",
    "zh-Hant": "Traditional Chinese (zh-Hant)",
    "en": "English",
    "en-GB": "British English (en-GB)",
    "en-US": "American English (en-US)",
    "ja": "Japanese",
    "ko": "Korean",
    "pt-PT": "European Portuguese (Portugal, pt-PT)",
    "pt-BR": "Brazilian Portuguese (pt-BR)",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ru": "Russian",
    "ar": "Arabic",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
}

_SUPPORTED_TAGS = {tag for tag, _ in SUPPORTED_LANGUAGES}
_PRIMARY_ONLY_LANGUAGES = frozenset(tag for tag, _ in TRANSLATION_LANGUAGES if tag != AUTO and "-" not in tag)
_DEFAULT_TAG = "en"
_BCP47_TAG_RE = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")


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


def normalize_translation_language(locale_name: str) -> str:
    """Normalize a BCP-47 / POSIX locale string while keeping regional variants.

    Returns ``en`` when the input is empty or not a valid BCP-47 language tag.
    """
    cleaned = locale_name.strip().split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    if not cleaned or not _BCP47_TAG_RE.fullmatch(cleaned):
        return _DEFAULT_TAG

    parts = cleaned.split("-")
    primary = parts[0].lower()
    rest = [part.lower() for part in parts[1:]]

    if primary == "zh":
        if any(part in ("hant", "tw", "hk", "mo") for part in rest):
            return "zh-Hant"
        return "zh-Hans"

    if primary == "pt":
        return "pt-BR" if "br" in rest else "pt-PT"

    if primary in _PRIMARY_ONLY_LANGUAGES:
        if primary == "en" and "gb" in rest:
            return "en-GB"
        return primary

    canonical_parts: list[str] = [primary]
    for subtag in rest:
        if len(subtag) == 4 and subtag.isalpha():
            canonical_parts.append(subtag.title())
        elif len(subtag) == 2 and subtag.isalpha():
            canonical_parts.append(subtag.upper())
        else:
            canonical_parts.append(subtag)
    return "-".join(canonical_parts)


def _system_locale_name(locale_name: str | None = None) -> str:
    """Return an explicit test locale or the active Qt system locale."""
    if locale_name is not None:
        return locale_name
    from PyQt6.QtCore import QLocale

    return QLocale.system().name()


def system_translation_language(locale_name: str | None = None) -> str:
    """Resolve the system's preferred translation language as an Apple tag.

    ``locale_name`` is injectable for testing; when omitted it is read from
    :class:`PyQt6.QtCore.QLocale`.
    """
    return normalize_to_apple_tag(_system_locale_name(locale_name))


def resolve_translation_language(value: str, locale_name: str | None = None) -> str:
    """Turn a config value (``auto`` or an explicit tag) into a concrete Apple tag."""
    if not value or value == AUTO:
        return system_translation_language(locale_name)
    return normalize_to_apple_tag(value)


def resolve_lyrics_translation_language(value: str, locale_name: str | None = None) -> str:
    """Resolve ``auto`` or a user tag into a concrete BCP-47 lyrics target tag."""
    if not value or value.strip().lower() == AUTO:
        return normalize_translation_language(_system_locale_name(locale_name))
    return normalize_translation_language(value)


def language_prompt_label(tag: str) -> str:
    """Return a clear English language description for LLM translation prompts."""
    normalized = normalize_translation_language(tag)
    return _LANGUAGE_ENGLISH_NAMES.get(normalized, normalized)


def translation_language_display_name(tag: str) -> str:
    """Return the full human-readable language name for a BCP-47 tag."""
    normalized = normalize_translation_language(tag)
    return _LANGUAGE_DISPLAY_NAMES.get(normalized, normalized)


__all__ = [
    "AUTO",
    "SUPPORTED_LANGUAGES",
    "TRANSLATION_LANGUAGES",
    "language_prompt_label",
    "normalize_to_apple_tag",
    "normalize_translation_language",
    "resolve_lyrics_translation_language",
    "resolve_translation_language",
    "system_translation_language",
    "translation_language_display_name",
]
