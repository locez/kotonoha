"""Built-in OpenAI-compatible presets and endpoint URL validation."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .models import TranslationError, TranslationErrorKind

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class OpenAIPreset:
    """One selectable OpenAI-compatible provider preset offered in Settings."""

    preset_id: str
    base_url: str
    default_model: str
    requires_api_key: bool = True


OPENAI_PRESETS: tuple[OpenAIPreset, ...] = (
    OpenAIPreset(
        preset_id="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-3.5-flash-lite",
    ),
    OpenAIPreset(
        preset_id="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-flash",
    ),
    OpenAIPreset(
        preset_id="openrouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="google/gemini-3.5-flash-lite",
    ),
    OpenAIPreset(
        preset_id="ollama",
        base_url="http://localhost:11434/v1",
        default_model="gemma3",
        requires_api_key=False,
    ),
    OpenAIPreset(
        preset_id="custom",
        base_url="",
        default_model="",
    ),
)

_PRESETS_BY_ID: dict[str, OpenAIPreset] = {preset.preset_id: preset for preset in OPENAI_PRESETS}


def preset_by_id(preset_id: str) -> OpenAIPreset | None:
    """Return one built-in OpenAI-compatible preset by its stable identifier."""
    return _PRESETS_BY_ID.get(preset_id)


def match_preset_id(base_url: str) -> str:
    """Return the built-in preset matching ``base_url``, or ``custom``."""
    normalized = base_url.strip().rstrip("/").lower()
    for preset in OPENAI_PRESETS:
        if preset.base_url and preset.base_url.rstrip("/").lower() == normalized:
            return preset.preset_id
    return "custom"


def is_loopback_url(url: str) -> bool:
    """Return whether ``url`` targets a local loopback host."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def validate_base_url(url: str) -> str:
    """Validate and normalize an OpenAI-compatible API base URL.

    Remote hosts require ``https``; plain ``http`` is permitted only for local
    loopback hosts such as Ollama or llama.cpp. Embedded credentials, queries,
    and fragments are rejected.
    """
    cleaned = url.strip()
    if not cleaned:
        raise TranslationError("Translation API base URL is empty", kind=TranslationErrorKind.CONFIG)
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise TranslationError("Translation API base URL must include a host", kind=TranslationErrorKind.CONFIG)
    if parsed.username is not None or parsed.password is not None:
        raise TranslationError(
            "Translation API base URL must not embed credentials",
            kind=TranslationErrorKind.CONFIG,
        )
    if parsed.query or parsed.fragment:
        raise TranslationError(
            "Translation API base URL must not contain query parameters or fragments",
            kind=TranslationErrorKind.CONFIG,
        )
    if scheme == "https":
        return cleaned.rstrip("/")
    if scheme == "http" and host in _LOOPBACK_HOSTS:
        return cleaned.rstrip("/")
    raise TranslationError(
        "Translation API base URL must use https:// (or http://localhost for local models)",
        kind=TranslationErrorKind.CONFIG,
    )


__all__ = [
    "OPENAI_PRESETS",
    "OpenAIPreset",
    "is_loopback_url",
    "match_preset_id",
    "preset_by_id",
    "validate_base_url",
]
