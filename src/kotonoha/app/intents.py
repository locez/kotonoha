"""Typed commands crossing from presentation into application workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from ..config import Config, TranslationProvider
from ..config.schema import SETTINGS_CONFIG_FIELDS
from ..display.offsets import TrackOffsetKey
from ..lyrics.cache import LyricsCacheKey, LyricsCacheQuery
from ..lyrics.search import LyricsSearchQuery, LyricsSearchResult
from ..translation import TranslationCacheKey, TranslationCacheQuery


@dataclass(frozen=True, slots=True)
class ApplyConfig:
    """Apply a complete form value set and its effective user changes.

    The complete ``Config`` keeps the intent easy to inspect. ``changed_fields``
    lets the application merge the form with newer runtime-owned values when the
    dialog stayed open.
    """

    config: Config
    changed_fields: frozenset[str] = frozenset(SETTINGS_CONFIG_FIELDS)


@dataclass(frozen=True, slots=True)
class ClearCache:
    """Remove persisted lyrics cache entries."""


@dataclass(frozen=True, slots=True)
class ClearTranslationCache:
    """Remove persisted API-translated lyric entries without deleting source lyrics."""


@dataclass(frozen=True, slots=True)
class OpenTranslationCacheManagement:
    """Open the standalone translation-cache management window."""


@dataclass(frozen=True, slots=True)
class SearchTranslationCache:
    """Search persisted translation cache metadata using user criteria."""

    query: TranslationCacheQuery


@dataclass(frozen=True, slots=True)
class DeleteTranslationCacheEntries:
    """Delete the exact translation cache entries selected by the user."""

    keys: tuple[TranslationCacheKey, ...]


@dataclass(frozen=True, slots=True)
class LoadTranslationCacheRecord:
    """Load one cached translation's full line list for editing."""

    key: TranslationCacheKey


@dataclass(frozen=True, slots=True)
class UpdateTranslationCacheEntry:
    """Persist user-edited translation lines for one cached entry."""

    key: TranslationCacheKey
    translations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SaveTranslationApiKey:
    """Persist one provider API key into the system keyring."""

    provider: TranslationProvider
    api_key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DeleteTranslationApiKey:
    """Remove one provider API key from the system keyring."""

    provider: TranslationProvider


@dataclass(frozen=True, slots=True)
class OpenCacheManagement:
    """Open the separate local lyrics cache management window."""


@dataclass(frozen=True, slots=True)
class SearchCache:
    """Search cache metadata using the query entered by the user."""

    query: LyricsCacheQuery


@dataclass(frozen=True, slots=True)
class DeleteCacheEntries:
    """Delete the exact cache rows selected in the management window."""

    keys: tuple[LyricsCacheKey, ...]


@dataclass(frozen=True, slots=True)
class RequestRestart:
    """Restart the process after settings that require it are applied."""


@dataclass(frozen=True, slots=True)
class ChangeTrackOffset:
    """Persist one display timing correction for a structured lyric timeline key."""

    key: TrackOffsetKey
    offset_ms: int


@dataclass(frozen=True, slots=True)
class ChangePosition:
    """Persist a platform-accepted output-local overlay placement."""

    margin_edge: int
    margin_x: int
    screen_name: str
    screen_width: int
    screen_height: int


@dataclass(frozen=True, slots=True)
class SearchLyrics:
    """Search configured lyric providers for the editable query fields."""

    query: LyricsSearchQuery


@dataclass(frozen=True, slots=True)
class SelectLyrics:
    """Persist the exact lyric result explicitly selected by the user."""

    result: LyricsSearchResult


SettingsIntent: TypeAlias = (
    ApplyConfig
    | ClearCache
    | ClearTranslationCache
    | OpenTranslationCacheManagement
    | SearchTranslationCache
    | LoadTranslationCacheRecord
    | UpdateTranslationCacheEntry
    | DeleteTranslationCacheEntries
    | SaveTranslationApiKey
    | DeleteTranslationApiKey
    | OpenCacheManagement
    | SearchCache
    | DeleteCacheEntries
    | RequestRestart
    | ChangeTrackOffset
    | ChangePosition
)

LyricsSearchIntent: TypeAlias = SearchLyrics | SelectLyrics

__all__ = [
    "ApplyConfig",
    "ChangePosition",
    "ChangeTrackOffset",
    "ClearCache",
    "ClearTranslationCache",
    "DeleteCacheEntries",
    "DeleteTranslationApiKey",
    "DeleteTranslationCacheEntries",
    "LoadTranslationCacheRecord",
    "OpenCacheManagement",
    "OpenTranslationCacheManagement",
    "RequestRestart",
    "SaveTranslationApiKey",
    "SearchCache",
    "SearchLyrics",
    "SearchTranslationCache",
    "SelectLyrics",
    "UpdateTranslationCacheEntry",
    "LyricsSearchIntent",
    "SettingsIntent",
]
