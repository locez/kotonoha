"""OpenAI-compatible Chat Completions translator (Gemini, DeepSeek, OpenRouter, Ollama)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence

from ..config.models import DEFAULT_TRANSLATION_PROMPT
from ..i18n import language_prompt_label
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
from .presets import is_loopback_url, validate_base_url

DEFAULT_OPENAI_TIMEOUT_S = 25.0
FALLBACK_OPENAI_TIMEOUT_S = 15.0
_MAX_CHUNK_LINES = 80


def chat_completions_endpoint(base_url: str) -> str:
    """Resolve one validated OpenAI-compatible base URL to its chat-completions URL."""
    normalized = validate_base_url(base_url)
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


class OpenAICompatibleTranslator:
    """Translate lyric lines via any OpenAI ``/chat/completions`` compatible endpoint."""

    def __init__(
        self,
        session: LyricsSession,
        *,
        base_url: str,
        model: str,
        style_prompt: str = "",
        timeout_s: float = DEFAULT_OPENAI_TIMEOUT_S,
        transient_retry_delay_s: float = DEFAULT_TRANSIENT_RETRY_DELAY_S,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._model = model.strip()
        self._style_prompt = style_prompt.strip()
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
        """Translate ``request.lines`` into ``request.target_language`` with strict id alignment."""
        endpoint = chat_completions_endpoint(self._base_url)
        if not self._model:
            raise TranslationError("Translation model name is empty", kind=TranslationErrorKind.CONFIG)
        cleaned_key = api_key.strip()
        if not cleaned_key and not is_loopback_url(endpoint):
            raise TranslationError(
                "Translation API key is required for remote endpoints",
                kind=TranslationErrorKind.AUTH,
            )
        if not request.lines:
            return TranslationResult((), provider="openai-compatible", model=self._model)

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if cleaned_key:
            headers["Authorization"] = f"Bearer {cleaned_key}"

        translated: list[str] = []
        for start in range(0, len(request.lines), _MAX_CHUNK_LINES):
            chunk = request.lines[start : start + _MAX_CHUNK_LINES]
            translated.extend(
                await self._translate_chunk(
                    endpoint,
                    headers,
                    chunk,
                    target_language=request.target_language,
                    title=request.title,
                    artist=request.artist,
                )
            )

        return TranslationResult(
            translations=tuple(translated),
            provider="openai-compatible",
            model=self._model,
        )

    async def _translate_chunk(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        lines: Sequence[str],
        *,
        target_language: str,
        title: str,
        artist: str,
    ) -> list[str]:
        messages = _build_messages(
            lines,
            target_language=target_language,
            title=title,
            artist=artist,
            style_prompt=self._style_prompt,
        )
        body: dict[str, object] = {
            "model": self._model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        payload = await self._post_chat(
            endpoint,
            headers,
            body,
            allow_retry_without_format=True,
            retries_on_503=1,
        )
        content = _extract_message_content(payload)
        return _parse_aligned_translations(content, expected_count=len(lines))

    async def _post_chat(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        body: dict[str, object],
        *,
        allow_retry_without_format: bool,
        retries_on_503: int = 0,
    ) -> object:
        should_retry_503 = False
        fallback_body: dict[str, object] | None = None
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
                        format_http_error("Translation API rejected the API key", status, detail),
                        kind=TranslationErrorKind.AUTH,
                    )
                if status == 429:
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("Translation API rate limit exceeded", status, detail),
                        kind=TranslationErrorKind.RATE_LIMIT,
                        retryable=True,
                    )
                if status == 400 and allow_retry_without_format and "response_format" in body:
                    fallback_body = dict(body)
                    fallback_body.pop("response_format", None)
                elif status == 503 and retries_on_503 > 0:
                    should_retry_503 = True
                elif status >= 500:
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("Translation API server error", status, detail),
                        kind=TranslationErrorKind.NETWORK,
                        retryable=True,
                    )
                elif status >= 400:
                    detail = await read_error_summary(response)
                    raise TranslationError(
                        format_http_error("Translation API request failed", status, detail),
                        kind=TranslationErrorKind.INVALID_RESPONSE,
                    )
                else:
                    return await read_json_capped(response, "OpenAI-compatible API", max_bytes=MAX_RESPONSE_BYTES)
        except LyricsHttpError as exc:
            raise TranslationError(
                f"Translation HTTP request failed: {exc}",
                kind=TranslationErrorKind.NETWORK,
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise TranslationError(
                "Translation API request timed out",
                kind=TranslationErrorKind.NETWORK,
                retryable=True,
            ) from exc
        except ValueError as exc:
            raise TranslationError(
                f"Translation API returned invalid JSON: {exc}",
                kind=TranslationErrorKind.INVALID_RESPONSE,
            ) from exc

        if fallback_body is not None:
            return await self._post_chat(
                endpoint,
                headers,
                fallback_body,
                allow_retry_without_format=False,
                retries_on_503=retries_on_503,
            )
        if should_retry_503:
            if self._transient_retry_delay_s > 0:
                await asyncio.sleep(self._transient_retry_delay_s)
            return await self._post_chat(
                endpoint,
                headers,
                body,
                allow_retry_without_format=allow_retry_without_format,
                retries_on_503=retries_on_503 - 1,
            )
        raise TranslationError("Translation API request did not complete", kind=TranslationErrorKind.NETWORK)


def _build_messages(
    lines: Sequence[str],
    *,
    target_language: str,
    title: str,
    artist: str,
    style_prompt: str = "",
) -> list[dict[str, str]]:
    target_label = language_prompt_label(target_language)
    style = style_prompt.strip() or DEFAULT_TRANSLATION_PROMPT
    system_prompt = (
        f"You translate song lyrics into {target_label}. "
        f"{style} "
        'Return ONLY a valid JSON object of the form {"translations": {"0": "...", "1": "..."}} '
        "with every numeric string key from the input present and no extra commentary."
    )
    user_payload: dict[str, object] = {
        "target_language": target_label,
        "lines": {str(index): text for index, text in enumerate(lines)},
    }
    if title.strip():
        user_payload["title"] = title.strip()
    if artist.strip():
        user_payload["artist"] = artist.strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _extract_message_content(payload: object) -> str:
    if not isinstance(payload, Mapping):
        raise TranslationError("Translation response root is not an object", kind=TranslationErrorKind.INVALID_RESPONSE)
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise TranslationError("Translation response has no choices", kind=TranslationErrorKind.INVALID_RESPONSE)
    first = choices[0]
    if not isinstance(first, Mapping):
        raise TranslationError("Translation choice is not an object", kind=TranslationErrorKind.INVALID_RESPONSE)
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise TranslationError("Translation choice is missing message", kind=TranslationErrorKind.INVALID_RESPONSE)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        joined = "".join(parts).strip()
        if joined:
            return joined
    raise TranslationError("Translation response message content is empty", kind=TranslationErrorKind.INVALID_RESPONSE)


def _strip_json_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        cleaned = cleaned.removesuffix("```")
    cleaned = cleaned.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _parse_aligned_translations(raw_content: str, *, expected_count: int) -> list[str]:
    try:
        parsed = json.loads(_strip_json_fences(raw_content))
    except json.JSONDecodeError as exc:
        raise TranslationError(
            f"Model output is not valid JSON: {exc}",
            kind=TranslationErrorKind.INVALID_RESPONSE,
        ) from exc

    if not isinstance(parsed, Mapping):
        raise TranslationError("Model JSON output is not an object", kind=TranslationErrorKind.INVALID_RESPONSE)

    container = parsed.get("translations") if "translations" in parsed else parsed
    if isinstance(container, Sequence) and not isinstance(container, (str, bytes)):
        if len(container) != expected_count or not all(isinstance(item, str) for item in container):
            raise TranslationError(
                f"Model returned {len(container)} translations for {expected_count} lines",
                kind=TranslationErrorKind.INVALID_RESPONSE,
            )
        return [item.strip() for item in container]

    if not isinstance(container, Mapping):
        raise TranslationError("Model JSON translations field is invalid", kind=TranslationErrorKind.INVALID_RESPONSE)

    results: list[str] = []
    for index in range(expected_count):
        value = container.get(str(index))
        if not isinstance(value, str):
            raise TranslationError(
                f"Model output is missing translation for line {index}",
                kind=TranslationErrorKind.INVALID_RESPONSE,
            )
        results.append(value.strip())
    return results


__all__ = [
    "DEFAULT_OPENAI_TIMEOUT_S",
    "DEFAULT_TRANSIENT_RETRY_DELAY_S",
    "FALLBACK_OPENAI_TIMEOUT_S",
    "OpenAICompatibleTranslator",
    "chat_completions_endpoint",
]
