"""Typed contracts and pure text transforms for lyrics translation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..config.models import TranslationPolicy, TranslationProvider
from .language_detect import (
    detect_primary_language,
    existing_translation_matches_target,
    looks_like_target_language,
)

CONTENT_HASH_VERSION = "v1"


class TranslationErrorKind(StrEnum):
    """Normalized failure categories surfaced across translation providers."""

    AUTH = "auth"
    RATE_LIMIT = "rate-limit"
    CONFIG = "config"
    NETWORK = "network"
    INVALID_RESPONSE = "invalid-response"
    UNSUPPORTED_LANGUAGE = "unsupported-language"


class TranslationError(RuntimeError):
    """A provider or configuration error normalized at the translation boundary."""

    def __init__(
        self,
        message: str,
        *,
        kind: TranslationErrorKind,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TranslationConfig:
    """Immutable runtime settings consumed by the lyrics translation service."""

    policy: TranslationPolicy = TranslationPolicy.OFF
    provider: TranslationProvider = TranslationProvider.OPENAI_COMPATIBLE
    target_language: str = "en"
    base_url: str = ""
    model: str = ""
    prompt: str = ""
    cache_enabled: bool = True


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    """One deduplicated batch of lyric lines to translate into one target tag."""

    lines: tuple[str, ...]
    target_language: str
    title: str = ""
    artist: str = ""


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Validated line-aligned translations returned by a translator or cache."""

    translations: tuple[str, ...]
    provider: str
    model: str
    from_cache: bool = False


@dataclass(frozen=True, slots=True)
class TranslationCacheKey:
    """Stable identity of one cached lyric translation."""

    content_hash: str
    target_language: str


@dataclass(frozen=True, slots=True)
class TranslationCacheQuery:
    """User-facing search filter for persisted translation cache entries."""

    keyword: str = ""
    target_language: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationCacheEntry:
    """Metadata exposed to the translation-cache management window."""

    key: TranslationCacheKey
    title: str
    artist: str
    provider: str
    model: str
    line_count: int
    created_at: float
    last_accessed: float


class TranslationCacheDeleteStatus(StrEnum):
    """Outcome of deleting one persisted translation entry."""

    DELETED = "deleted"
    NOT_FOUND = "not-found"


@dataclass(frozen=True, slots=True)
class TranslationCacheDeleteResult:
    """Report whether one requested cached translation was actually removed."""

    key: TranslationCacheKey
    status: TranslationCacheDeleteStatus


@dataclass(frozen=True, slots=True)
class TranslationCacheRecord:
    """Full line-by-line payload of one cached translation for inspection and editing."""

    entry: TranslationCacheEntry
    source_lines: tuple[str, ...]
    translations: tuple[str, ...]
    timestamps: tuple[float, ...] = ()


class TranslatorPort(Protocol):
    """Provider-neutral async translation boundary."""

    async def translate(
        self,
        request: TranslationRequest,
        *,
        api_key: str,
    ) -> TranslationResult:
        """Translate ``request.lines`` into ``request.target_language``."""
        ...


def content_hash(lines: Sequence[str]) -> str:
    """Hash the ordered lyric text so cached translations stay line-aligned."""
    joined = "\n".join(lines)
    digest = hashlib.sha256(f"{CONTENT_HASH_VERSION}\0{joined}".encode())
    return digest.hexdigest()


def deduplicate_lines(lines: Sequence[str]) -> tuple[tuple[str, ...], tuple[int | None, ...]]:
    """Collapse repeated non-empty lines while keeping an exact positional map.

    Whitespace-only lines map to ``None`` so they are never sent over the wire
    and always reconstruct as empty strings.
    """
    unique: list[str] = []
    index_by_text: dict[str, int] = {}
    mapping: list[int | None] = []
    for raw in lines:
        cleaned = raw.strip()
        if not cleaned:
            mapping.append(None)
            continue
        existing = index_by_text.get(cleaned)
        if existing is None:
            existing = len(unique)
            index_by_text[cleaned] = existing
            unique.append(cleaned)
        mapping.append(existing)
    return tuple(unique), tuple(mapping)


def reconstruct_lines(
    unique_translations: Sequence[str],
    mapping: Sequence[int | None],
) -> tuple[str, ...]:
    """Expand deduplicated translations back to the exact original line count."""
    output: list[str] = []
    for index in mapping:
        if index is None:
            output.append("")
            continue
        if index < 0 or index >= len(unique_translations):
            raise ValueError("translation reconstruction index is out of range")
        output.append(unique_translations[index].strip())
    return tuple(output)


__all__ = [
    "CONTENT_HASH_VERSION",
    "TranslationCacheDeleteResult",
    "TranslationCacheDeleteStatus",
    "TranslationCacheEntry",
    "TranslationCacheKey",
    "TranslationCacheQuery",
    "TranslationCacheRecord",
    "TranslationConfig",
    "TranslationError",
    "TranslationErrorKind",
    "TranslationRequest",
    "TranslationResult",
    "TranslatorPort",
    "content_hash",
    "deduplicate_lines",
    "detect_primary_language",
    "existing_translation_matches_target",
    "looks_like_target_language",
    "reconstruct_lines",
]
