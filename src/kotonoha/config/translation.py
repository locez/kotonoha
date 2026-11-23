"""Typed translation-service configuration models and normalization."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_TRANSLATION_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_TRANSLATION_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TRANSLATION_PROMPT = (
    "Preserve poetic tone, nuance, idioms, and natural expressions used in the target language. "
    "Keep each translated line concise for a desktop lyrics overlay. "
    "If a line is already in the target language or is pure vocalization/punctuation, keep it natural as-is."
)

_SERVICE_ID_RE = re.compile(r"[^a-z0-9-]+")


class TranslationPolicy(StrEnum):
    """When API translation is invoked for a displayed lyric document."""

    OFF = "off"
    MISSING_ONLY = "missing-only"
    REPLACE = "replace"


class TranslationProvider(StrEnum):
    """Supported API translation backends."""

    OPENAI_COMPATIBLE = "openai-compatible"
    DEEPL = "deepl"


@dataclass(frozen=True, slots=True)
class TranslationServiceConfig:
    """One prioritized translation service entry persisted in ``config.json``.

    API keys are stored separately in the OS keyring under
    ``translation_api_key.<id>`` and are never written to configuration files.
    """

    id: str
    name: str
    provider: TranslationProvider = TranslationProvider.OPENAI_COMPATIBLE
    enabled: bool = True
    base_url: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize into a plain JSON-compatible dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider.value,
            "enabled": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
        }


DEFAULT_TRANSLATION_SERVICES: tuple[TranslationServiceConfig, ...] = (
    TranslationServiceConfig(
        id="gemini",
        name="Google Gemini (AI Studio)",
        provider=TranslationProvider.OPENAI_COMPATIBLE,
        enabled=True,
        base_url=DEFAULT_TRANSLATION_BASE_URL,
        model=DEFAULT_TRANSLATION_MODEL,
    ),
    TranslationServiceConfig(
        id="deepl",
        name="DeepL API",
        provider=TranslationProvider.DEEPL,
        enabled=False,
    ),
)


def default_translation_services() -> list[TranslationServiceConfig]:
    """Return a fresh mutable copy of the default prioritized services list."""
    return list(DEFAULT_TRANSLATION_SERVICES)


def sanitize_service_id(raw: str, *, fallback: str = "service") -> str:
    """Normalize a translation service identifier for stable keyring lookup."""
    cleaned = _SERVICE_ID_RE.sub("-", raw.strip().lower()).strip("-")
    return cleaned[:40] if cleaned else fallback


def next_unique_service_id(base: str, existing_ids: Sequence[str]) -> str:
    """Return ``base`` or a numbered suffix not present in ``existing_ids``."""
    stem = sanitize_service_id(base)
    taken = set(existing_ids)
    if stem not in taken:
        return stem
    index = 2
    while f"{stem}-{index}" in taken:
        index += 1
    return f"{stem}-{index}"


def clean_translation_services(value: object) -> list[TranslationServiceConfig]:
    """Validate and deduplicate persisted translation service entries."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return default_translation_services()
    cleaned: list[TranslationServiceConfig] = []
    seen_ids: list[str] = []
    for item in value:
        parsed = _parse_service(item, seen_ids)
        if parsed is None:
            continue
        seen_ids.append(parsed.id)
        cleaned.append(parsed)
    return cleaned if cleaned else default_translation_services()


def migrate_legacy_translation_services(data: Mapping[str, object]) -> list[TranslationServiceConfig] | None:
    """Convert pre-list single-provider settings into ordered service entries.

    TODO: Remove once pre-release single-provider config files from PR #116
    testing are no longer in use.
    """
    legacy_keys = ("translation_provider", "translation_base_url", "translation_model")
    if "translation_services" in data or not any(key in data for key in legacy_keys):
        return None
    raw_provider = data.get("translation_provider")
    provider = (
        TranslationProvider.DEEPL
        if raw_provider == TranslationProvider.DEEPL.value
        else TranslationProvider.OPENAI_COMPATIBLE
    )
    raw_url = data.get("translation_base_url")
    base_url = raw_url.strip() if isinstance(raw_url, str) and raw_url.strip() else DEFAULT_TRANSLATION_BASE_URL
    raw_model = data.get("translation_model")
    model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else DEFAULT_TRANSLATION_MODEL

    if provider is TranslationProvider.DEEPL:
        return [
            TranslationServiceConfig(
                id="deepl",
                name="DeepL API",
                provider=TranslationProvider.DEEPL,
                enabled=True,
            ),
            TranslationServiceConfig(
                id="openai-compatible",
                name=_infer_openai_name(base_url),
                provider=TranslationProvider.OPENAI_COMPATIBLE,
                enabled=False,
                base_url=base_url,
                model=model,
            ),
        ]
    return [
        TranslationServiceConfig(
            id="openai-compatible",
            name=_infer_openai_name(base_url),
            provider=TranslationProvider.OPENAI_COMPATIBLE,
            enabled=True,
            base_url=base_url,
            model=model,
        ),
        TranslationServiceConfig(
            id="deepl",
            name="DeepL API",
            provider=TranslationProvider.DEEPL,
            enabled=False,
        ),
    ]


def _parse_service(item: object, seen_ids: Sequence[str]) -> TranslationServiceConfig | None:
    if isinstance(item, TranslationServiceConfig):
        service_id = next_unique_service_id(item.id or item.provider.value, seen_ids)
        provider = item.provider
        name = item.name.strip() or _default_service_name(provider, item.base_url)
        enabled = bool(item.enabled)
        base_url = item.base_url.strip() if provider is TranslationProvider.OPENAI_COMPATIBLE else ""
        model = item.model.strip() if provider is TranslationProvider.OPENAI_COMPATIBLE else ""
        return TranslationServiceConfig(
            id=service_id,
            name=name,
            provider=provider,
            enabled=enabled,
            base_url=base_url,
            model=model,
        )
    if not isinstance(item, Mapping):
        return None
    raw_provider = item.get("provider")
    if raw_provider == TranslationProvider.DEEPL.value:
        provider = TranslationProvider.DEEPL
    elif raw_provider == TranslationProvider.OPENAI_COMPATIBLE.value:
        provider = TranslationProvider.OPENAI_COMPATIBLE
    else:
        return None
    is_openai = provider is TranslationProvider.OPENAI_COMPATIBLE
    raw_url = item.get("base_url")
    base_url = raw_url.strip() if is_openai and isinstance(raw_url, str) else ""
    raw_model = item.get("model")
    model = raw_model.strip() if is_openai and isinstance(raw_model, str) else ""
    raw_name = item.get("name")
    name = (
        raw_name.strip()
        if isinstance(raw_name, str) and raw_name.strip()
        else _default_service_name(provider, base_url)
    )
    raw_id = item.get("id")
    seed_id = raw_id if isinstance(raw_id, str) and raw_id.strip() else provider.value
    service_id = next_unique_service_id(seed_id, seen_ids)
    raw_enabled = item.get("enabled")
    if isinstance(raw_enabled, bool):
        enabled = raw_enabled
    elif isinstance(raw_enabled, int) and raw_enabled in (0, 1):
        enabled = bool(raw_enabled)
    else:
        enabled = True
    return TranslationServiceConfig(
        id=service_id,
        name=name,
        provider=provider,
        enabled=enabled,
        base_url=base_url,
        model=model,
    )


def _default_service_name(provider: TranslationProvider, base_url: str) -> str:
    if provider is TranslationProvider.DEEPL:
        return "DeepL API"
    return _infer_openai_name(base_url)


def _infer_openai_name(base_url: str) -> str:
    lowered = base_url.strip().lower()
    if "generativelanguage.googleapis.com" in lowered:
        return "Google Gemini (AI Studio)"
    if "api.deepseek.com" in lowered:
        return "DeepSeek"
    if "openrouter.ai" in lowered:
        return "OpenRouter"
    if "localhost:11434" in lowered or "127.0.0.1:11434" in lowered:
        return "Ollama (Local)"
    return "OpenAI-compatible API"


__all__ = [
    "DEFAULT_TRANSLATION_BASE_URL",
    "DEFAULT_TRANSLATION_MODEL",
    "DEFAULT_TRANSLATION_PROMPT",
    "DEFAULT_TRANSLATION_SERVICES",
    "TranslationPolicy",
    "TranslationProvider",
    "TranslationServiceConfig",
    "clean_translation_services",
    "default_translation_services",
    "migrate_legacy_translation_services",
    "next_unique_service_id",
    "sanitize_service_id",
]
