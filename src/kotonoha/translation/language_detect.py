"""Word-equivalent and line-majority language detection for lyrics translation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache

from ..i18n import normalize_translation_language

_LATIN_WORD_RE = re.compile(r"[a-zA-Z\u00c0-\u024f']+")
_CYRILLIC_WORD_RE = re.compile(r"[\u0400-\u04ff]+")
_ARABIC_WORD_RE = re.compile(r"[\u0600-\u06ff]+")
_UKRAINIAN_CHARS = frozenset("іїєґІЇЄҐ")
_RUSSIAN_CHARS = frozenset("ыэёъЫЭЁЪ")

# Compact high-precision stopword sets used to distinguish major Latin-script languages.
_LATIN_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "the", "and", "you", "that", "was", "for", "are", "with", "his", "they",
            "this", "have", "from", "your", "what", "when", "will", "just", "know",
            "don't", "i'm", "it's", "we're", "can't", "won't", "there", "where",
            "were", "been", "into", "about", "because", "through", "never", "always",
            "my", "me", "we", "our", "out", "all", "not", "but", "she", "her", "him",
        }
    ),
    "pt": frozenset(
        {
            "não", "você", "para", "com", "uma", "mais", "como", "mas", "foi", "são",
            "estou", "meu", "minha", "isso", "tudo", "quando", "porque", "onde",
            "sem", "pelo", "pela", "dos", "das", "nós", "eles", "elas", "também",
            "ainda", "só", "já", "até", "aqui", "agora", "assim", "muito", "que",
            "seu", "sua", "teu", "tua", "eu", "ele", "ela", "nos", "num", "numa",
        }
    ),
    "es": frozenset(
        {
            "que", "los", "las", "una", "por", "con", "para", "pero", "como", "más",
            "todo", "esta", "este", "cuando", "donde", "porque", "sin", "sobre",
            "entre", "eres", "estoy", "tengo", "quiero", "siempre", "nunca", "tú",
            "mí", "qué", "del", "al", "yo", "ella", "ellos", "nos", "mis", "tus",
            "sus", "muy", "aquí", "ahora", "nada", "bien",
        }
    ),
    "fr": frozenset(
        {
            "les", "des", "une", "que", "qui", "dans", "pour", "pas", "sur", "avec",
            "plus", "mais", "tout", "fait", "comme", "bien", "nous", "vous", "ils",
            "elles", "suis", "sont", "être", "avoir", "cette", "mon", "ton", "son",
            "mes", "tes", "ses", "je", "tu", "ne", "où", "été", "cœur", "sans",
            "chez", "est", "aux", "moi", "toi",
        }
    ),
    "de": frozenset(
        {
            "und", "die", "der", "das", "nicht", "ich", "ein", "eine", "mit", "auf",
            "für", "ist", "sind", "war", "von", "dem", "den", "des", "sich", "aus",
            "wie", "aber", "noch", "nur", "auch", "wenn", "dann", "wir", "ihr",
            "sie", "mein", "dein", "sein", "dich", "mich", "dir", "mir", "über",
            "durch", "wieder", "immer", "du", "es", "zu",
        }
    ),
    "it": frozenset(
        {
            "che", "non", "per", "una", "con", "come", "più", "ma", "tutto", "questa",
            "questo", "sono", "siamo", "sei", "mio", "mia", "tuoi", "suoi", "nel",
            "nella", "delle", "degli", "alla", "dallo", "anche", "sempre", "mai",
            "quando", "dove", "perché", "senza", "cuore", "notte", "vita", "io",
            "tu", "noi", "voi", "loro", "gli", "tra", "fra",
        }
    ),
}


def _is_han(code: int) -> bool:
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2A6DF
        or code in (0x3005, 0x3007)
    )


def _is_kana(code: int) -> bool:
    return (
        0x3041 <= code <= 0x3096
        or 0x30A1 <= code <= 0x30FA
        or 0x31F0 <= code <= 0x31FF
        or 0xFF66 <= code <= 0xFF9D
    )


def _is_hangul(code: int) -> bool:
    return 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F


@lru_cache(maxsize=4096)
def _classify_han_script(char: str) -> str | None:
    """Classify one Han character as Simplified-only, Traditional-only, or shared.

    Uses Python's built-in GB2312 (Simplified) and Big5 (Traditional) codec
    repertoires: characters encodable only in GB2312 signal Simplified Chinese
    (``zh-Hans``), while characters encodable only in Big5 signal Traditional
    Chinese (``zh-Hant``).
    """
    try:
        char.encode("gb2312")
        in_gb2312 = True
    except UnicodeEncodeError:
        in_gb2312 = False
    try:
        char.encode("big5")
        in_big5 = True
    except UnicodeEncodeError:
        in_big5 = False
    if in_gb2312 and not in_big5:
        return "zh-Hans"
    if in_big5 and not in_gb2312:
        return "zh-Hant"
    return None


def _detect_chinese_script(hans_count: int, hant_count: int, total_han: int) -> str:
    """Return ``zh-Hans``, ``zh-Hant``, or script-neutral ``zh``."""
    if hans_count >= 2 and hans_count >= hant_count * 2:
        return "zh-Hans"
    if hant_count >= 2 and hant_count >= hans_count * 2:
        return "zh-Hant"
    if hans_count >= 1 and hant_count == 0 and total_han <= 16:
        return "zh-Hans"
    if hant_count >= 1 and hans_count == 0 and total_han <= 16:
        return "zh-Hant"
    return "zh"


def detect_primary_language(lines: Sequence[str]) -> str | None:
    """Detect the dominant primary language tag of a lyric document, or ``None``.

    Counts Latin/Cyrillic/Arabic text as whole words rather than individual
    characters so bilingual credits (e.g. ``Mixing Engineer: ...``) or English
    chorus hooks do not drown out CJK/Hangul lyrics. Distinguishes Simplified
    (``zh-Hans``) and Traditional (``zh-Hant``) Chinese when script markers are
    present.
    """
    total_han = 0
    total_kana = 0
    total_hangul = 0
    total_thai = 0
    total_latin_words = 0
    total_cyrillic_words = 0
    total_arabic_words = 0
    hans_markers = 0
    hant_markers = 0
    uk_markers = 0
    ru_markers = 0

    votes: dict[str, int] = {
        "zh": 0,
        "ja": 0,
        "ko": 0,
        "cyrillic": 0,
        "ar": 0,
        "th": 0,
        "latin": 0,
    }
    latin_words: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        han = 0
        kana = 0
        hangul = 0
        thai = 0
        for char in line:
            code = ord(char)
            if _is_han(code):
                han += 1
                script = _classify_han_script(char)
                if script == "zh-Hans":
                    hans_markers += 1
                elif script == "zh-Hant":
                    hant_markers += 1
            elif _is_kana(code):
                kana += 1
            elif _is_hangul(code):
                hangul += 1
            elif 0x0E00 <= code <= 0x0E7F:
                thai += 1
            elif char in _UKRAINIAN_CHARS:
                uk_markers += 1
            elif char in _RUSSIAN_CHARS:
                ru_markers += 1

        line_latin = _LATIN_WORD_RE.findall(line.lower())
        line_cyrillic = _CYRILLIC_WORD_RE.findall(line)
        line_arabic = _ARABIC_WORD_RE.findall(line)
        n_latin = len(line_latin)
        n_cyrillic = len(line_cyrillic)
        n_arabic = len(line_arabic)

        total_han += han
        total_kana += kana
        total_hangul += hangul
        total_thai += thai
        total_latin_words += n_latin
        total_cyrillic_words += n_cyrillic
        total_arabic_words += n_arabic
        latin_words.extend(line_latin)

        cjk = han + kana
        if hangul >= 2 and hangul >= n_latin and hangul >= cjk:
            votes["ko"] += 1
        elif cjk >= 2 and cjk >= n_latin and cjk >= hangul:
            if kana >= 2 or (kana >= 1 and (kana / cjk) >= 0.15):
                votes["ja"] += 1
            else:
                votes["zh"] += 1
        elif n_cyrillic >= 2 and n_cyrillic >= n_latin:
            votes["cyrillic"] += 1
        elif n_arabic >= 2 and n_arabic >= n_latin:
            votes["ar"] += 1
        elif thai >= 4 and thai >= n_latin:
            votes["th"] += 1
        elif n_latin >= 2:
            votes["latin"] += 1

    total_units = (
        total_han
        + total_kana
        + total_hangul
        + total_thai
        + total_latin_words
        + total_cyrillic_words
        + total_arabic_words
    )
    voted_lines = sum(votes.values())
    if total_units < 4 or voted_lines == 0:
        return None

    if total_hangul >= 6 and (
        votes["ko"] / voted_lines >= 0.40 or total_hangul / total_units >= 0.40
    ):
        return "ko"

    total_cjk = total_han + total_kana
    cjk_lines = votes["ja"] + votes["zh"]
    if total_cjk >= 6 and (cjk_lines / voted_lines >= 0.40 or total_cjk / total_units >= 0.40):
        kana_share = total_kana / total_cjk
        if total_kana >= 6 and kana_share >= 0.10:
            return "ja"
        if total_hangul / total_units < 0.05 and kana_share < 0.05:
            return _detect_chinese_script(hans_markers, hant_markers, total_han)

    if total_cyrillic_words >= 4 and (
        votes["cyrillic"] / voted_lines >= 0.45 or total_cyrillic_words / total_units >= 0.45
    ):
        return "uk" if uk_markers > ru_markers and uk_markers > 0 else "ru"

    if total_arabic_words >= 4 and (
        votes["ar"] / voted_lines >= 0.45 or total_arabic_words / total_units >= 0.45
    ):
        return "ar"

    if total_thai >= 6 and (
        votes["th"] / voted_lines >= 0.45 or total_thai / total_units >= 0.45
    ):
        return "th"

    if votes["latin"] / voted_lines >= 0.50 or total_latin_words / total_units >= 0.55:
        return _detect_latin_language(latin_words)

    return None


def _detect_latin_language(words: Sequence[str]) -> str | None:
    if len(words) < 8:
        return None
    ranked = sorted(
        (
            (sum(1 for word in words if word in stopwords), lang)
            for lang, stopwords in _LATIN_STOPWORDS.items()
        ),
        reverse=True,
    )
    best_hits, best_lang = ranked[0]
    second_hits = ranked[1][0]
    if best_hits < 3 or (best_hits / len(words)) < 0.12:
        return None
    if best_hits >= second_hits + 2 and best_hits >= second_hits * 1.5:
        return best_lang
    return None


def looks_like_target_language(
    lines: Sequence[str],
    target_language: str,
    *,
    document_language: str | None = None,
) -> bool:
    """Return True when ``lines`` are already written in ``target_language``."""
    target_norm = normalize_translation_language(target_language)
    target_primary = target_norm.split("-", 1)[0].lower()

    if document_language and document_language.strip():
        doc_norm = normalize_translation_language(document_language)
        doc_primary = doc_norm.split("-", 1)[0].lower()
        if doc_norm == target_norm:
            return True
        if doc_primary == target_primary and target_primary != "pt":
            return True

    detected = detect_primary_language(lines)
    if detected is None:
        return False
    detected_primary = detected.split("-", 1)[0].lower()
    return detected == target_norm or detected_primary == target_primary


def existing_translation_matches_target(
    translations: Sequence[str],
    target_language: str,
) -> bool:
    """Decide whether provider-supplied translations already match ``target_language``.

    Returns ``True`` when the existing translations match ``target_language`` OR
    cannot be confidently classified as a different language/script, so
    ``missing-only`` never discards ambiguous provider translations unnecessarily.
    Distinguishes Simplified (``zh-Hans``) and Traditional (``zh-Hant``) Chinese
    so switching between them re-translates provider-supplied Chinese lines.
    """
    detected = detect_primary_language(translations)
    if detected is None:
        return True
    target_norm = normalize_translation_language(target_language)
    target_primary = target_norm.split("-", 1)[0].lower()
    detected_primary = detected.split("-", 1)[0].lower()
    if detected_primary != target_primary:
        return False
    if target_primary == "zh" and detected in {"zh-Hans", "zh-Hant"}:
        return detected == target_norm
    return True


__all__ = [
    "detect_primary_language",
    "existing_translation_matches_target",
    "looks_like_target_language",
]
