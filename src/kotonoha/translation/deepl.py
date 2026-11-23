"""DeepL official API translator supporting Free (:fx) and Pro endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from ..i18n import normalize_translation_language
from ..lyrics.http import LyricsHttpError, LyricsSession
from ..lyrics.payload import MAX_RESPONSE_BYTES, read_json_capped
from .models import (
    DEFAULT_TRANSIENT_RETRY_DELAY_S,
    TranslationError,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
    format_http_error,
    read_error_summary,
)

DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"
DEEPL_MAX_TEXTS_PER_REQUEST = 50
DEFAULT_DEEPL_TIMEOUT_S = 15.0

_DEEPL_TARGET_MAP: dict[str, str] = {
    "ar": "AR",
    "bg": "BG",
    "cs": "CS",
    "da": "DA",
    "de": "DE",
    "el": "EL",
    "en": "EN-US",
    "en-GB": "EN-GB",
    "en-US": "EN-US",
    "es": "ES",
    "et": "ET",
    "fi": "FI",
    "fr": "FR",
    "hu": "HU",
    "id": "ID",
    "it": "IT",
    "ja": "JA",
    "ko": "KO",
    "lt": "LT",
    "lv": "LV",
    "nb": "NB",
    "nl": "NL",
    "no": "NB",
    "pl": "PL",
    "pt": "PT-PT",
    "pt-BR": "PT-BR",
    "pt-PT": "PT-PT",
    "ro": "RO",
    "ru": "RU",
    "sk": "SK",
    "sl": "SL",
    "sv": "SV",
    "th": "TH",
    "tr": "TR",
    "uk": "UK",
    "vi": "VI",
    "zh": "ZH-HANS",
    "zh-Hans": "ZH-HANS",
    "zh-Hant": "ZH-HANT",
}


def deepl_endpoint_for_key(api_key: str) -> str:
    """Route ``:fx`` keys to DeepL API Free and all other keys to DeepL API Pro."""
    cleaned = api_key.strip()
    if not cleaned:
        raise TranslationError("DeepL API key is missing", kind=TranslationErrorKind.AUTH)
    return DEEPL_FREE_URL if cleaned.endswith(":fx") else DEEPL_PRO_URL


def map_deepl_target_lang(language: str) -> str:
    """Map a normalized BCP-47 tag to a DeepL ``target_lang`` code."""
    normalized = normalize_translation_language(language)
    mapped = _DEEPL_TARGET_MAP.get(normalized)
    if mapped is not None:
        return mapped
    primary = normalized.split("-", 1)[0].lower()
    mapped = _DEEPL_TARGET_MAP.get(primary)
    if mapped is not None:
        return mapped
    raise TranslationError(
        f"DeepL does not support target language {language!r}",
        kind=TranslationErrorKind.UNSUPPORTED_LANGUAGE,
    )


class DeepLTranslator:
    """Translate lyric line batches through DeepL's official REST API."""

    def __init__(
        self,
        session: LyricsSession,
        *,
        timeout_s: float = DEFAULT_DEEPL_TIMEOUT_S,
        transient_retry_delay_s: float = DEFAULT_TRANSIENT_RETRY_DELAY_S,
    ) -> None:
        self._session = session
        self._timeout_s = timeout_s
        self._transient_retry_delay_s = max(0.0, transient_retry_delay_s)

    @property
    def timeout_s(self) -> float:
        """Return the per-request total HTTP timeout in seconds."""
        return self._timeout_s

    async def translate(
        self,
        request: TranslationRequest,
        *,
        api_key: str,
    ) -> TranslationResult:
        """Translate all lines in ``request`` using bounded batches of 50 texts."""
        cleaned_key = api_key.strip()
        endpoint = deepl_endpoint_for_key(cleaned_key)
        target_lang = map_deepl_target_lang(request.target_language)
        if not request.lines:
            return TranslationResult((), provider="deepl", model=_deepl_plan_label(cleaned_key))

        context = _lyric_context(request.title, request.artist)
        translated: list[str] = []
        headers = {
            "Authorization": f"DeepL-Auth-Key {cleaned_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for start in range(0, len(request.lines), DEEPL_MAX_TEXTS_PER_REQUEST):
            batch = request.lines[start : start + DEEPL_MAX_TEXTS_PER_REQUEST]
            body: dict[str, object] = {
                "text": list(batch),
                "target_lang": target_lang,
                "preserve_formatting": True,
            }
            if context:
                body["context"] = context
            translated.extend(await self._translate_batch(endpoint, headers, body, expected_count=len(batch)))

        return TranslationResult(
            translations=tuple(translated),
            provider="deepl",
            model=_deepl_plan_label(cleaned_key),
        )

    async def _translate_batch(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        *,
        expected_count: int,
        retries_on_503: int = 1,
    ) -> list[str]:
        should_retry_503 = False
        try:
            async with self._session.post(
                endpoint,
                json=body,
                headers=headers,
                timeout=self._timeout_s,
            ) as response:
                status = response.status
                if status in (401, 403):
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("DeepL rejected the API key", status, detail),
                        kind=TranslationErrorKind.AUTH,
                    )
                if status in (429, 456):
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("DeepL rate limit or monthly character quota exceeded", status, detail),
                        kind=TranslationErrorKind.RATE_LIMIT,
                        retryable=True,
                    )
                if status == 503 and retries_on_503 > 0:
                    should_retry_503 = True
                elif status >= 500:
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("DeepL service error", status, detail),
                        kind=TranslationErrorKind.NETWORK,
                        retryable=True,
                    )
                elif status >= 400:
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("DeepL request failed", status, detail),
                        kind=TranslationErrorKind.INVALID_RESPONSE,
                    )
                else:
                    payload = await read_json_capped(response, "DeepL API", max_bytes=MAX_RESPONSE_BYTES)
                    return _parse_deepl_response(payload, expected_count=expected_count)
        except LyricsHttpError as exc:
            raise TranslationError(
                f"DeepL HTTP request failed: {exc}",
                kind=TranslationErrorKind.NETWORK,
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise TranslationError(
                "DeepL translation request timed out",
                kind=TranslationErrorKind.NETWORK,
                retryable=True,
            ) from exc
        except ValueError as exc:
            raise TranslationError(
                f"DeepL returned an invalid payload: {exc}",
                kind=TranslationErrorKind.INVALID_RESPONSE,
            ) from exc

        if should_retry_503:
            if self._transient_retry_delay_s > 0:
                await asyncio.sleep(self._transient_retry_delay_s)
            return await self._translate_batch(
                endpoint,
                headers,
                body,
                expected_count=expected_count,
                retries_on_503=retries_on_503 - 1,
            )
        raise TranslationError("DeepL translation request did not complete", kind=TranslationErrorKind.NETWORK)


def _deepl_plan_label(api_key: str) -> str:
    return "deepl-free" if api_key.endswith(":fx") else "deepl-pro"


def _lyric_context(title: str, artist: str) -> str:
    parts = [part.strip() for part in (title, artist) if part.strip()]
    if not parts:
        return "Song lyrics. Translate naturally and preserve idioms."
    return f"Song lyrics for {' - '.join(parts)}. Translate naturally and preserve idioms."


def _parse_deepl_response(payload: object, *, expected_count: int) -> list[str]:
    if not isinstance(payload, Mapping):
        raise TranslationError("DeepL response root is not an object", kind=TranslationErrorKind.INVALID_RESPONSE)
    raw_items = payload.get("translations")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise TranslationError(
            "DeepL response is missing the translations list",
            kind=TranslationErrorKind.INVALID_RESPONSE,
        )
    if len(raw_items) != expected_count:
        raise TranslationError(
            f"DeepL returned {len(raw_items)} translations for {expected_count} lines",
            kind=TranslationErrorKind.INVALID_RESPONSE,
        )
    results: list[str] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise TranslationError(
                "DeepL translation item is not an object",
                kind=TranslationErrorKind.INVALID_RESPONSE,
            )
        text = item.get("text")
        if not isinstance(text, str):
            raise TranslationError(
                "DeepL translation item has non-string text",
                kind=TranslationErrorKind.INVALID_RESPONSE,
            )
        results.append(text.strip())
    return results


__all__ = [
    "DEEPL_FREE_URL",
    "DEEPL_MAX_TEXTS_PER_REQUEST",
    "DEEPL_PRO_URL",
    "DeepLTranslator",
    "deepl_endpoint_for_key",
    "map_deepl_target_lang",
]
